"""Mini moteur de gabarits Go (sous-ensemble utilisé par le chart) : de quoi RENDRE le chart pour le valider.
Ce n'est PAS Helm : il ne gère que les constructions employées ici (valeurs, if, range, quote, toYaml, nindent).
Utilisé par check_chart.py ; pour la vérité, lance `helm lint` et `helm template`."""
import json, re, yaml

TOKEN = re.compile(r"\{\{(-)?\s*(.*?)\s*(-)?\}\}", re.S)

def tokenize(src):
    out, pos = [], 0
    for m in TOKEN.finditer(src):
        text = src[pos:m.start()]
        if m.group(1): text = text.rstrip()
        out.append(("text", text)); out.append(("tag", m.group(2)))
        pos = m.end()
        if m.group(3):
            nxt = src[pos:]; pos += len(nxt) - len(nxt.lstrip())
    out.append(("text", src[pos:]))
    return out

def parse(tokens):
    root, stack = [], []
    cur = root
    for kind, val in tokens:
        if kind == "text":
            cur.append(("text", val)); continue
        if val.startswith("if "):
            node = ("if", val[3:].strip(), []); cur.append(node); stack.append(cur); cur = node[2]
        elif val.startswith("range "):
            node = ("range", val[6:].strip(), []); cur.append(node); stack.append(cur); cur = node[2]
        elif val == "end":
            cur = stack.pop()
        else:
            cur.append(("expr", val))
    assert not stack, "bloc non fermé"
    return root

def lookup(path, ctx):
    if path.startswith("$"): return ctx["vars"][path]
    if path.startswith('"'): return json.loads(path)
    if re.fullmatch(r"-?\d+", path): return int(path)
    cur = ctx
    for part in path.lstrip(".").split("."): cur = cur[part]
    return cur

def to_s(v):
    if isinstance(v, bool): return "true" if v else "false"
    return str(v)

def apply_filter(v, f):
    if f == "quote": return json.dumps(to_s(v), ensure_ascii=False)
    if f == "toYaml": return yaml.safe_dump(v, default_flow_style=False, sort_keys=True).rstrip("\n")
    m = re.fullmatch(r"nindent (\d+)", f)
    if m:
        pad = " " * int(m.group(1))
        return "\n" + "\n".join(pad + line for line in str(v).split("\n"))
    raise ValueError(f"filtre non géré : {f}")

def eval_expr(expr, ctx):
    parts = [p.strip() for p in expr.split("|")]
    words = parts[0].split(None, 1)
    if words[0] in ("quote", "toYaml") and len(words) == 2:
        v = apply_filter(lookup(words[1], ctx), words[0])
    else:
        v = lookup(parts[0], ctx)
    for f in parts[1:]: v = apply_filter(v, f)
    return to_s(v)

def render_nodes(nodes, ctx):
    out = []
    for n in nodes:
        if n[0] == "text": out.append(n[1])
        elif n[0] == "expr": out.append(eval_expr(n[1], ctx))
        elif n[0] == "if":
            if bool(lookup(n[1], ctx)): out.append(render_nodes(n[2], ctx))
        elif n[0] == "range":
            m = re.fullmatch(r"(\$\w+)(?:\s*,\s*(\$\w+))?\s*:=\s*(.+)", n[1])
            a, b, path = m.group(1), m.group(2), m.group(3)
            coll = lookup(path, ctx)
            items = sorted(coll.items()) if isinstance(coll, dict) else list(enumerate(coll or []))
            for k, v in items:
                sub = dict(ctx, vars=dict(ctx["vars"]))
                if b: sub["vars"][a], sub["vars"][b] = k, v
                else: sub["vars"][a] = v
                out.append(render_nodes(n[2], sub))
    return "".join(out)

def render(src, values, release):
    return render_nodes(parse(tokenize(src)), {"Values": values, "Release": release, "vars": {}})

def deep_set(d, dotted, value):
    keys = dotted.split("."); cur = d
    for k in keys[:-1]: cur = cur.setdefault(k, {})
    cur[keys[-1]] = value
