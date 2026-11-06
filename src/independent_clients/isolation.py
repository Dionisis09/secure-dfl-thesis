"""Fail-closed Linux filesystem sandbox plus non-dumpable process memory.

The trusted launcher/host administrator remains outside this boundary. Landlock
restrictions are inherited by children and cannot be removed by this process.
"""
import ctypes
import errno
import os
import platform
import sys
from pathlib import Path


def protect_memory():
    if sys.platform != 'linux':
        raise RuntimeError('independent-client isolation requires Linux')
    libc = ctypes.CDLL(None, use_errno=True)
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if libc.prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE
        raise OSError(ctypes.get_errno(), 'cannot disable process dumping')
    return libc


def restrict_files(private_dir, extra_read=(), *, gpu=False,connect_ports=(),bind_ports=()):
    libc = protect_memory()
    # Landlock restricts the calling thread and its future children, not existing
    # sibling threads. Refuse an already multithreaded startup instead of leaving
    # a native worker outside the filesystem boundary.
    if len(list(Path('/proc/self/task').iterdir())) != 1:
        raise RuntimeError('Landlock requires a single-threaded startup')
    if platform.machine() not in ('x86_64', 'aarch64'):
        raise RuntimeError('unvalidated Landlock syscall architecture')
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 4:
        raise RuntimeError('Landlock ABI >=4 is required; refusing unsandboxed execution')
    handled = (1 << 15) - 1

    class Ruleset(ctypes.Structure):
        _fields_ = [('handled_access_fs', ctypes.c_uint64),('handled_access_net',ctypes.c_uint64)]

    class PathBeneath(ctypes.Structure):
        _pack_ = 1
        _fields_ = [('allowed_access', ctypes.c_uint64), ('parent_fd', ctypes.c_int32)]

    class NetPort(ctypes.Structure):
        _fields_ = [('allowed_access',ctypes.c_uint64),('port',ctypes.c_uint64)]

    attr = Ruleset(handled,3)  # Deny TCP bind/connect except explicitly enrolled ports.
    fd = libc.syscall(444, ctypes.byref(attr), ctypes.sizeof(attr), 0)
    if fd < 0:
        raise OSError(ctypes.get_errno(), 'cannot create Landlock ruleset')
    try:
        def allow(path, writable=False, executable=False):
            path = Path(path).resolve()
            if not path.exists():
                return
            rights = (4 | 8) if path.is_dir() else 4
            if writable:
                rights = handled & ~1 if path.is_dir() else (2 | 4 | (1 << 14))
            if executable:
                rights |= 1
            parent = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = PathBeneath(rights, parent)
                if libc.syscall(445, fd, 1, ctypes.byref(rule), 0) != 0:
                    raise OSError(ctypes.get_errno(), 'cannot add Landlock path')
            finally:
                os.close(parent)

        # Read-only software/runtime roots, never the user's entire home/workspace.
        paths = ['/usr', '/lib', '/lib64', '/etc/ld.so.cache', '/etc/localtime',
                 '/etc/ssl', '/etc/hosts', '/etc/nsswitch.conf', '/etc/resolv.conf',
                 sys.prefix, sys.base_prefix, Path(__file__).resolve().parents[1],
                 Path(__file__).resolve().parents[2]/'scripts',
                 '/proc/cpuinfo','/proc/meminfo','/sys/devices/system/cpu',
                 f'/proc/{os.getpid()}', *extra_read]
        for path in paths:
            allow(path)
        for path in ['/dev/null', '/dev/urandom', '/dev/random']:
            allow(path, writable=True)
        if gpu:
            allow('/proc/driver/nvidia')
            for path in Path('/dev').glob('nvidia*'):
                allow(path, writable=True)
            allow('/sys/devices', executable=False)
        allow(private_dir, writable=True)
        for ports,right in [(connect_ports,2),(bind_ports,1)]:
            for port in sorted(set(ports)):
                if type(port)!=int or not 1024<=port<=65535:raise RuntimeError('invalid enrolled TCP port')
                rule=NetPort(right,port)
                if libc.syscall(445,fd,2,ctypes.byref(rule),0)!=0:
                    raise OSError(ctypes.get_errno(),'cannot add Landlock TCP rule')
        if libc.prctl(38, 1, 0, 0, 0) != 0:  # PR_SET_NO_NEW_PRIVS
            raise OSError(ctypes.get_errno(), 'cannot set no_new_privs')
        if libc.syscall(446, fd, 0) != 0:
            raise OSError(ctypes.get_errno(), 'cannot enforce Landlock')
    finally:
        os.close(fd)
    restrict_syscalls(libc)
    return dict(landlock_abi=abi,filesystem_restricted=True,non_dumpable=True,
                core_dumps_disabled=True,host_admin_is_trusted=True,
                tcp_ports_restricted=True,unix_sockets_blocked=True,seccomp_enforced=True)


def restrict_syscalls(libc):
    """Block local control-plane IPC and routes around the filesystem/TCP rules.

    In particular, an unrestricted Unix socket to the same-UID systemd user
    manager could otherwise launch a process outside this sandbox. TCP-only
    sockets plus enrolled Landlock ports close that confused-deputy route.
    """
    machine=platform.machine()
    if machine=='x86_64':
        arch=0xc000003e;socket_number=41
        denied=[53,59,322,101,310,311,321,298,308,272,165,166,155,303,304,312,323,
                90,268,92,93,94,260,188,189,190,197,198,199]
    elif machine=='aarch64':
        arch=0xc00000b7;socket_number=198
        denied=[199,221,281,117,270,271,280,241,268,97,40,39,41,264,265,272,282,
                53,54,55,5,6,7,14,15,16]
    else:raise RuntimeError('unsupported seccomp architecture')
    denied += [425,426,427,428,429,430,431,432,433,438,442,452]
    # Classic BPF: load arch, kill foreign ABIs; reject x32; then syscall filters.
    LD=0x20;JEQ=0x15;JSET=0x45;AND=0x54;RET=0x06
    DENY=0x00050000|errno.EPERM;ALLOW=0x7fff0000
    program=[(LD,0,0,4),(JEQ,1,0,arch),(RET,0,0,0x80000000),
             (LD,0,0,0),(JSET,0,1,0x40000000),(RET,0,0,DENY)]
    for number in denied:program += [(JEQ,0,1,number),(RET,0,0,DENY)]
    socket_rules=[(LD,0,0,16),(JEQ,2,0,2),(JEQ,1,0,10),(RET,0,0,DENY),
                  (LD,0,0,24),(AND,0,0,15),(JEQ,1,0,1),(RET,0,0,DENY),
                  (LD,0,0,32),(JEQ,2,0,0),(JEQ,1,0,6),(RET,0,0,DENY),(RET,0,0,ALLOW)]
    program += [(JEQ,0,len(socket_rules),socket_number),*socket_rules,(RET,0,0,ALLOW)]
    class Filter(ctypes.Structure):
        _fields_=[('code',ctypes.c_ushort),('jt',ctypes.c_ubyte),('jf',ctypes.c_ubyte),('k',ctypes.c_uint)]
    class Program(ctypes.Structure):
        _fields_=[('length',ctypes.c_ushort),('filters',ctypes.POINTER(Filter))]
    array=(Filter*len(program))(*(Filter(*instruction) for instruction in program))
    descriptor=Program(len(program),array)
    if libc.prctl(22,2,ctypes.byref(descriptor),0,0)!=0:  # PR_SET_SECCOMP, FILTER
        raise OSError(ctypes.get_errno(),'cannot enforce syscall filter')


def denied_probes(paths, pids):
    """Run inside the restricted coordinator; raise if any cross-client read works."""
    results = []
    for path in paths:
        try:
            with open(path, 'rb') as stream:
                stream.read(1)
        except PermissionError:
            results.append(dict(kind='private_file_read', denied=True))
        else:
            raise RuntimeError('client private file was readable')
    libc = ctypes.CDLL(None, use_errno=True)
    class IOVec(ctypes.Structure):
        _fields_ = [('base', ctypes.c_void_p), ('length', ctypes.c_size_t)]
    for pid in pids:
        buffer = ctypes.create_string_buffer(1)
        local = IOVec(ctypes.cast(buffer, ctypes.c_void_p), 1)
        remote = IOVec(1, 1)
        ctypes.set_errno(0)
        result = libc.process_vm_readv(int(pid), ctypes.byref(local), 1,
                                      ctypes.byref(remote), 1, 0)
        if result != -1 or ctypes.get_errno() != errno.EPERM:
            raise RuntimeError('cross-client memory read was not denied by permissions')
        results.append(dict(kind='process_vm_readv', denied=True))
    return results
