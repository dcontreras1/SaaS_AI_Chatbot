import unicodedata

def normalize_text(text):
    if not isinstance(text, str):
        return ""
    text = unicodedata.normalize('NFD', text)
    text = text.encode('ascii', 'ignore').decode('utf-8')
    text = text.lower().strip()
    return " ".join(text.split())

def match_option(user_input, options):
    user_norm = normalize_text(user_input)
    for opt in options:
        opt_norm = normalize_text(opt)
        if user_norm == opt_norm or opt_norm in user_norm:
            return opt
    return None