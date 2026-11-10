"""Temporary Windows idle-sleep inhibition, scoped to one running controller."""
import argparse
import ctypes
import datetime
import json
import os
import time
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('--pid',type=int,required=True)
p.add_argument('--deadline',required=True)
p.add_argument('--receipt',required=True)
a=p.parse_args()
if os.name!='nt' or a.pid<=0:
    raise SystemExit('Requires a valid owned Windows controller PID')
deadline=datetime.datetime.fromisoformat(a.deadline).timestamp()
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32]
k.OpenProcess.restype=ctypes.c_void_p
k.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
k.CloseHandle.argtypes=[ctypes.c_void_p]
k.SetThreadExecutionState.argtypes=[ctypes.c_uint32]
k.SetThreadExecutionState.restype=ctypes.c_uint32
handle=k.OpenProcess(0x100000,False,a.pid)
if not handle:
    raise SystemExit('Controller is not running; no power request made')
receipt=Path(a.receipt)
def record(active,reason):
    value=dict(active=active,reason=reason,controller_PID=a.pid,deadline=a.deadline,
               updated_UTC=datetime.datetime.now(datetime.timezone.utc).isoformat(),
               display_required=False,permanent_power_settings_changed=False)
    temp=receipt.with_suffix('.tmp')
    temp.write_text(json.dumps(value,indent=2))
    os.replace(temp,receipt)
try:
    if not k.SetThreadExecutionState(0x80000001):
        raise ctypes.WinError(ctypes.get_last_error())
    record(True,'controller_running_system_idle_sleep_inhibited')
    while time.time()<deadline:
        result=k.WaitForSingleObject(handle,10000)
        if result==0:
            break
        if result!=0x102:
            raise ctypes.WinError(ctypes.get_last_error())
finally:
    k.SetThreadExecutionState(0x80000000)
    k.CloseHandle(handle)
    record(False,'controller_exited_or_deadline_reached_request_released')
