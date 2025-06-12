import unicodedata

def normalize_text(text):
    """Quita acentos, pasa a minúsculas y elimina espacios extra."""
    if not isinstance(text, str):
        return ""
    text = unicodedata.normalize('NFD', text)
    text = text.encode('ascii', 'ignore').decode('utf-8')
    text = text.lower().strip()
    return " ".join(text.split())

def match_option(user_input, options):
    """
    Busca si el input del usuario coincide (ignorando tildes/case/espacios) con alguna opción.
    Retorna la opción original si hay match, o None.
    """
    user_norm = normalize_text(user_input)
    for opt in options:
        if user_norm == normalize_text(opt):
            return opt
    return None