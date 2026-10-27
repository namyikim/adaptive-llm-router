# Historical Python runtime for tqdm-6. Build downloads preselected public packages.
# Third-party bug project source is NOT executed during image build.
FROM python:3.6.15-slim-buster
RUN python -m pip install --no-cache-dir \
    "pip==21.3.1" "setuptools==59.6.0" \
    "pytest==5.4.3" "six==1.15.0" "nose==1.3.7"
ENV PYTHONDONTWRITEBYTECODE=1
USER 65534:65534
