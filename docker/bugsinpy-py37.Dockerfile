# Historical Python 3.7 runtime for Tornado test replay.
# No project setup.sh or remote unpinned package installation is performed here.
FROM python:3.7.17-slim-buster
ENV PYTHONDONTWRITEBYTECODE=1
USER 65534:65534
