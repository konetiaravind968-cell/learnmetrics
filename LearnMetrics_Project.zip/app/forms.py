import re
from flask import request, url_for
from .db import execute
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
PAGE = 25

def F(n, l, t='text', r=False, o=None, lo=None, hi=None):
    return dict(n=n, l=l, t=t, r=r, o=o, lo=lo, hi=hi)

def read_form(fields, form):
    """Server-side validation. Returns (clean values, list of error messages)."""
    vals, errs = {}, []
    for f in fields:
        n, l, t = f['n'], f['l'], f['t']
        raw = (form.get(n) or '').strip()
        if t == 'checkbox':
            vals[n] = 1 if form.get(n) else 0; continue
        vals[n] = None
        if not raw:
            if f['r']: errs.append(f'{l} is required.')
            continue
        if t == 'number':
            try: v = float(raw)
            except ValueError: errs.append(f'{l} must be a number.'); continue
            if (f['lo'] is not None and v < f['lo']) or (f['hi'] is not None and v > f['hi']):
                errs.append(f'{l} is out of the allowed range.'); continue
            vals[n] = int(v) if v == int(v) else v
        elif t == 'email':
            if EMAIL_RE.match(raw): vals[n] = raw.lower()
            else: errs.append(f'{l} is not a valid email.')
        elif t == 'url':
            if re.match(r'https?://\S+$', raw, re.I): vals[n] = raw
            else: errs.append(f'{l} must start with http:// or https://')
        elif t == 'select':
            if raw in {str(v) for v, _ in f['o']}: vals[n] = raw
            else: errs.append(f'{l} has an invalid choice.')
        elif t == 'textarea': vals[n] = raw
        else: vals[n] = re.sub(r'\s+', ' ', raw)
    return vals, errs

def insert(table, vals):
    cols = list(vals)
    return execute(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join(['%s'] * len(cols))})", tuple(vals[c] for c in cols))

def update(table, rid, vals):
    cols = list(vals)
    return execute(f"UPDATE {table} SET {','.join(c + '=%s' for c in cols)} WHERE id=%s", tuple(vals[c] for c in cols) + (rid,))

def links(page, pages):
    def u(p):
        a = request.args.to_dict(); a['page'] = p
        return url_for(request.endpoint, **{**(request.view_args or {}), **a})
    return (u(page - 1) if page > 1 else None, u(page + 1) if page < pages else None)
