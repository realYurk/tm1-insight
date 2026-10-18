"""Bounded, secret-free connection diagnostics. Never bypass system proxies."""
from __future__ import annotations
import http.client
import socket
import ssl
import os
import urllib.request
import requests
from requests.auth import AuthBase


class NoAuth(AuthBase):
    def __call__(self,request):return request


def failure(stage, exc):
    """Only allowlisted fields, never str(exc), URLs, headers or config dumps."""
    chain=[];current=exc
    while current is not None and len(chain)<8 and id(current) not in {i for i,_ in chain}:
        chain.append((id(current),current));current=current.__cause__ or current.__context__
    values=[e for _,e in chain]
    status=getattr(exc,'status_code',None)
    if status is None and getattr(exc,'response',None) is not None:status=exc.response.status_code
    if isinstance(exc,MetadataFailure):return exc.record
    if any(isinstance(e,requests.exceptions.ProxyError) for e in values):kind='PROXY_ERROR'
    elif any(isinstance(e,ssl.SSLCertVerificationError) for e in values):kind='TLS_CERTIFICATE_ERROR'
    elif any(isinstance(e,(requests.exceptions.SSLError,ssl.SSLError)) for e in values):kind='TLS_ERROR'
    elif status==401:kind='AUTHENTICATION_FAILED'
    elif status==403:kind='PERMISSION_DENIED'
    elif status==404:kind='NOT_FOUND'
    elif status==407:kind='PROXY_AUTHENTICATION_REQUIRED'
    elif status in {400,405,406,415,422}:kind='REQUEST_OR_API_INCOMPATIBLE'
    elif status is not None:kind='HTTP_ERROR'
    elif any(isinstance(e,http.client.RemoteDisconnected) or type(e).__name__=='RemoteDisconnected' for e in values):kind='REMOTE_DISCONNECTED'
    elif any(isinstance(e,(TimeoutError,requests.exceptions.Timeout)) for e in values):kind='TIMEOUT'
    elif any(isinstance(e,socket.gaierror) for e in values):kind='DNS_ERROR'
    elif isinstance(exc,(ValueError,TypeError,KeyError)):kind='RESPONSE_OR_CONFIG_INVALID'
    else:kind='NETWORK_OR_CLIENT_ERROR'
    return dict(stage=stage,status='FAILED',category=kind,exception_types=[type(e).__name__ for e in values],
                **({'http_status':status} if type(status) is int else {}))


class MetadataFailure(RuntimeError):
    def __init__(self,stage,category,*,record=None):
        self.record=record or dict(stage=stage,status='FAILED',category=category)
        super().__init__(self.record['stage']+': '+self.record['category'])


def endpoint(settings):
    host=settings.tm1_address
    if not host or '://' in host or any(c in host for c in '/@?#\r\n') or not 0<settings.tm1_port<65536:
        raise MetadataFailure('CONFIG','INVALID_HOST_OR_REST_PORT')
    if ':' in host:host='['+host.strip('[]')+']'
    return f"{'https' if settings.tm1_ssl else 'http'}://{host}:{settings.tm1_port}/api/v1"


def verify_setting(settings):
    ca=getattr(settings,'tm1_ca_bundle',None) or os.environ.get('REQUESTS_CA_BUNDLE') or os.environ.get('CURL_CA_BUNDLE')
    if ca:
        from pathlib import Path
        if str(ca).casefold()=='false' or not Path(ca).is_file():
            raise MetadataFailure('CONFIG','TRUSTED_CA_FILE_REQUIRED')
    return str(ca) if ca else True


def diagnose(settings,*,timeout=5,cancel=None,probe_tls=True):
    if not 1<=timeout<=30:raise ValueError('timeout must be 1..30 seconds')
    def check():
        if cancel:cancel()
    result=dict(schema='tm1-readonly-diagnostic-1',stages=[],credentials_sent=False,
                protocol='https' if settings.tm1_ssl else 'http',proxy_bypass_override=False)
    try:root=endpoint(settings)
    except MetadataFailure as exc:result['stages'].append(exc.record);return result
    def run(stage,fn):
        check()
        try:record=fn();record=dict(stage=stage,status='OK',**(record or {}))
        except Exception as exc:record=failure(stage,exc)
        result['stages'].append(record);check();return record
    def tcp():
        with socket.create_connection((settings.tm1_address,settings.tm1_port),timeout=timeout):pass
    run('TCP',tcp)
    proxies=requests.utils.get_environ_proxies(root)
    result['proxy']=dict(system_proxy_registered=bool(urllib.request.getproxies()),
                         effective_proxy=bool(requests.utils.select_proxy(root,proxies)),
                         system_rules_unchanged=True)
    if settings.tm1_ssl or probe_tls:
        def tls():
            ca=verify_setting(settings)
            ctx=ssl.create_default_context(cafile=requests.certs.where() if ca is True else ca)
            with socket.create_connection((settings.tm1_address,settings.tm1_port),timeout=timeout) as raw:
                with ctx.wrap_socket(raw,server_hostname=settings.tm1_address) as conn:return dict(tls_version=conn.version())
        run('TLS_HANDSHAKE' if settings.tm1_ssl else 'TLS_PROTOCOL_PROBE_NO_AUTH',tls)
    def rest():
        # trust_env stays enabled: requests applies existing enterprise proxy rules.
        with requests.Session() as session:
            session.auth=NoAuth()  # prevent implicit .netrc auth while preserving proxy rules
            with session.get(root+'/Configuration/ProductVersion/$value',timeout=timeout,
                             verify=verify_setting(settings),allow_redirects=False,stream=True) as response:
                code=response.status_code
                if code==401:return dict(category='AUTHENTICATION_REQUIRED',http_status=code)
                if 300<=code<400:return dict(category='REDIRECT_REQUIRES_CONFIGURATION',http_status=code)
                response.raise_for_status()
                data=next(response.iter_content(256),b'')
                import re
                return dict(http_status=code,category='VERSION_RESPONSE' if re.match(rb'\s*\d+\.\d+',data) else 'NON_VERSION_RESPONSE')
    run('REST_VERSION_UNAUTHENTICATED',rest)
    return result
