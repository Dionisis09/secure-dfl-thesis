FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY secure_dfl_platform ./secure_dfl_platform
COPY keygen.py operator_dashboard.py verify_audit_logs.py compare_demo_stack_results.py tamper_audit_demo.py ./

EXPOSE 9000
CMD ["python", "-m", "secure_dfl_platform.server"]
