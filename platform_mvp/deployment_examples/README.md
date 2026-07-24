# Secure DFL Platform Deployment Examples

These files show how a small three-node deployment can be configured without
using deterministic demo identities.

## Steps

1. Generate keys:

```text
..\.venv\Scripts\python.exe keygen.py --nodes node0,node1,node2 --output-dir deployment_keys
```

2. Copy one `.env.example` file per node and adjust paths/ports.

3. Start each node in a separate terminal:

```text
python -m secure_dfl_platform.server
```

4. Start the dashboard:

```text
python operator_dashboard.py --nodes node0=http://127.0.0.1:9100,node1=http://127.0.0.1:9101,node2=http://127.0.0.1:9102 --admin-token local-dashboard-token
```

## Notes

These examples are local-development templates. Production deployment should add
TLS/mTLS, secret management, firewall rules, process supervision and persistent
monitoring.
