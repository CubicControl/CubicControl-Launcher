import os


def parse_server_properties(path: str) -> dict:
    """Parse a Minecraft server.properties-like file into a dict."""
    props = {}
    if not os.path.exists(path):
        return props

    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Handle commented lines like "#enable-rcon=true"
        is_commented = stripped.startswith('#')
        content = stripped[1:].strip() if is_commented else stripped

        if '=' in content:
            key, val = content.split('=', 1)
            key = key.strip()
            val = val.strip()
            if key and key not in props:
                props[key] = val

    return props


def parse_key_value_from_line(line: str) -> tuple[str | None, bool]:
    stripped = line.strip()
    if not stripped:
        return None, False
    is_commented = stripped.startswith('#')
    content = stripped[1:].strip() if is_commented else stripped
    if '=' in content:
        key, _ = content.split('=', 1)
        return key.strip(), is_commented
    return None, is_commented

def write_server_properties(path: str, new_values: dict):
    """
    Update or add the given keys in server.properties while preserving other lines.
    new_values is a dict like {"enable-rcon": "true", "rcon.port": "27001", ...}
    """
    lines = []
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

    remaining = dict(new_values)
    output_lines = []
    for line in lines:
        key, _ = parse_key_value_from_line(line)
        if key is None:
            output_lines.append(line)
        elif key in remaining:
            new_val = remaining.pop(key)
            output_lines.append(f"{key}={new_val}\n")
        else:
            output_lines.append(line)

    if remaining:
        if output_lines and not output_lines[-1].endswith('\n'):
            output_lines[-1] += '\n'
        output_lines.append("# Automatically added/updated by setup tool\n")
        for key, val in remaining.items():
            output_lines.append(f"{key}={val}\n")

    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(output_lines)
