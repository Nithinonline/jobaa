"""Normalize pasted job descriptions and safely fetch public HTTPS postings."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests

from core.file_parser import strip_html_to_text

MAX_JOB_PAGE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Job posting links must use HTTPS.")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Job posting links cannot include credentials or a custom port.")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("The job posting host could not be resolved.") from exc
    if not addresses:
        raise ValueError("The job posting host did not resolve to a public address.")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("Private or reserved network addresses are not allowed.")


def fetch_job_posting(url: str) -> str:
    """Fetch a bounded public job posting and convert HTML to readable text."""
    current_url = url.strip()
    if not current_url:
        raise ValueError("Provide a job posting URL.")

    for redirect_count in range(MAX_REDIRECTS + 1):
        _validate_public_url(current_url)
        response = requests.get(
            current_url,
            headers={"User-Agent": "JobaResumeTailor/1.0"},
            timeout=(5, 20),
            allow_redirects=False,
            stream=True,
        )
        try:
            if response.is_redirect:
                if redirect_count == MAX_REDIRECTS:
                    raise ValueError("The job posting URL redirected too many times.")
                location = response.headers.get("Location")
                if not location:
                    raise ValueError("The job posting returned an invalid redirect.")
                current_url = urljoin(current_url, location)
                continue
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                content.extend(chunk)
                if len(content) > MAX_JOB_PAGE_BYTES:
                    raise ValueError("The job posting page is larger than the 2 MB limit.")
            encoding = response.encoding or "utf-8"
            raw = bytes(content).decode(encoding, errors="replace")
            content_type = response.headers.get("Content-Type", "").lower()
            text = strip_html_to_text(raw) if "html" in content_type or "<html" in raw[:1000].lower() else raw
            if len(text.strip()) < 80:
                raise ValueError("The job posting page did not contain enough readable text.")
            return text.strip()
        finally:
            response.close()

    raise ValueError("The job posting could not be fetched.")
