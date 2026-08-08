import re

def validate_phone(phone):
    phone = phone.strip()
    if re.fullmatch(r'91\d{10}', phone):
        return True, phone
    if re.fullmatch(r'\d{10}', phone):
        return True, '91' + phone
    return False, None

def validate_email(email):
    return bool(re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email.strip()))

def validate_ip(ip):
    ip = ip.strip()
    if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip):
        return False
    parts = ip.split('.')
    return all(0 <= int(part) <= 255 for part in parts)

def validate_aadhaar(aadhaar):
    aadhaar = aadhaar.strip().replace(' ', '')
    return bool(re.fullmatch(r'\d{12}', aadhaar))

def validate_pan(pan):
    pan = pan.strip().upper()
    return bool(re.match(r'^[A-Z]{5}[0-9]{4}[A-Z]{1}$', pan))

def validate_domain(domain):
    domain = domain.strip().lower()
    return bool(re.match(r'^[a-z0-9]+([\-\.]{1}[a-z0-9]+)*\.[a-z]{2,}$', domain))

def make_line(text=None, char="─"):
    if text:
        length = len(text) + 4
    else:
        length = 30
    return char * length

def detect_search_type(query):
    query = query.strip()
    
    valid, processed = validate_phone(query)
    if valid:
        return 'phone', processed
    
    if validate_email(query):
        return 'email', query
    
    if validate_ip(query):
        return 'ip', query
    
    if validate_aadhaar(query):
        return 'aadhaar', query
    
    if validate_pan(query):
        return 'pan', query
    
    if validate_domain(query):
        return 'domain', query
    
    if re.match(r'^[A-Z]{2}[0-9]{2}[A-Z]{1,2}[0-9]{4}$', query.upper()):
        return 'vehicle', query.upper()
    
    if len(query) >= 3 and re.match(r'^[a-zA-Z\s\.]+$', query):
        return 'name', query
    
    if len(query) >= 3:
        return 'location', query
    
    return 'unknown', query