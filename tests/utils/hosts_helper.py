import textwrap

def write_hosts(tmp_path, content):
    """Write *content* to a temp file and return its path (str)."""
    p = tmp_path / 'hosts.txt'
    p.write_text(textwrap.dedent(content))
    return str(p)
