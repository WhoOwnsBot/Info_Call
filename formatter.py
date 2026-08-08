import re

class Formatter:
    """Complete OSINT formatter with all fields"""
    
    @staticmethod
    def clean_phone(phone):
        if phone and phone.startswith('91') and len(phone) == 12:
            return phone[2:]
        return phone
    
    @staticmethod
    def clean_address(address):
        if not address or address == "null":
            return None
        return ' '.join(address.split())
    
    @staticmethod
    def format_aadhaar(aadhaar):
        if not aadhaar or aadhaar == "null" or aadhaar == "":
            return "❌ Not Found"
        return aadhaar
    
    @staticmethod
    def get_sim_info(record):
        operator = record.get('Circle', record.get('Operator', ''))
        state = record.get('State', record.get('CircleState', ''))
        if operator and operator != "null" and state and state != "null":
            return f"{operator} ({state})"
        elif operator and operator != "null":
            return operator
        return None
    
    @staticmethod
    def get_relation_label(record, key, value):
        if not value or value == "null":
            return None
        value_lower = value.lower()
        address = record.get('Adres', record.get('Address', ''))
        
        if 'w/o' in value_lower or 'wife' in value_lower:
            return "Wife"
        if address and ('w/o' in address.lower() or 'wife' in address.lower()):
            return "Wife"
        
        female_indicators = ['devi', 'kumari', 'rani', 'bai']
        for indicator in female_indicators:
            if indicator in value_lower:
                return "Mother"
        return "Father"
    
    @staticmethod
    def deduplicate_records(records):
        seen = set()
        unique = []
        for record in records:
            name = record.get('FullName', record.get('Name', ''))
            phone = record.get('Phone', '')
            if name and name != "null" and phone and phone != "null":
                key = f"{name.strip()}|{phone.strip()}"
            elif name and name != "null":
                key = name.strip()
            elif phone and phone != "null":
                key = phone.strip()
            else:
                continue
            if key not in seen:
                seen.add(key)
                unique.append(record)
        return unique
    
    @staticmethod
    def is_empty_record(record):
        name = record.get('FullName', record.get('Name', ''))
        phone = record.get('Phone', '')
        if phone and phone != "null":
            if (not name or name == "null"):
                return True
        return False
    
    @staticmethod
    def get_relevance_score(record, query):
        score = 0
        query_clean = query[2:] if query.startswith('91') else query
        phone = record.get('Phone', '')
        if phone and query_clean in str(phone):
            score += 100
        if record.get('Aadhaar') and record.get('Aadhaar') != "null":
            score += 50
        return score
    
    @staticmethod
    def extract_address_parts(address):
        if not address:
            return None, None, None
        
        parts = address.split(',')
        parts = [p.strip() for p in parts if p.strip()]
        
        city = None
        state = None
        pin = None
        
        if len(parts) >= 3:
            city = parts[-3] if len(parts) >= 3 else None
            state = parts[-2] if len(parts) >= 2 else None
            pin = parts[-1] if len(parts) >= 1 else None
            
            if pin and not pin.isdigit():
                pin = None
        
        return city, state, pin
    
    @staticmethod
    def format_result(data, query, tokens_info=None):
        records = []
        for source_name, source_data in data.items():
            if isinstance(source_data, dict):
                recs = source_data.get("records", [])
                if recs:
                    records.extend([r for r in recs if isinstance(r, dict)])
        
        if not records:
            return "```\n🔍 RESULT: " + query + "\n━━━━━━━━━━━━━━━━━━━━━━━━\n❌ NO RESULTS FOUND\n\n💡 Suggestions:\n• Double check the number\n• Use 91 + 10 digits format\n• Try another number\n```"
        
        records = [r for r in records if not Formatter.is_empty_record(r)]
        records = Formatter.deduplicate_records(records)
        
        if not records:
            return "```\n🔍 RESULT: " + query + "\n━━━━━━━━━━━━━━━━━━━━━━━━\n❌ NO RESULTS FOUND\n\n💡 Suggestions:\n• Double check the number\n• Use 91 + 10 digits format\n• Try another number\n```"
        
        records.sort(key=lambda r: Formatter.get_relevance_score(r, query), reverse=True)
        records = records[:3]
        
        clean_query = Formatter.clean_phone(query)
        
        msg = []
        msg.append("```")
        msg.append("🔍 RESULT: " + clean_query)
        msg.append("━━━━━━━━━━━━━━━━━━━━━━━━")
        
        for idx, record in enumerate(records, 1):
            
            if idx == 1:
                msg.append("📌 PRIMARY RESULT")
            else:
                msg.append("📌 ADDITIONAL RESULT " + str(idx-1))
            msg.append("")
            
            # ========== 1. PERSONAL INFO ==========
            name = record.get('FullName', record.get('Name', ''))
            if name and name != "null":
                msg.append("👤 Name: " + name)
            else:
                msg.append("👤 Name: Not Available")
            
            # Father
            relation = record.get('FatherName', record.get('Fname', ''))
            if relation and relation != "null":
                label = Formatter.get_relation_label(record, 'FatherName', relation)
                msg.append("👨‍👦 " + label + ": " + relation)
            else:
                msg.append("👨‍👦 Father: Not Available")
            
            # ========== 2. CONTACT INFO ==========
            phone = record.get('Phone', '')
            if phone and phone != "null":
                msg.append("📱 Mobile: " + Formatter.clean_phone(phone))
            else:
                msg.append("📱 Mobile: Not Available")
            
            # Alternate numbers
            alts = []
            for key in ['Phone2', 'Phone3', 'Phone4', 'Phone5', 'Alternate']:
                val = record.get(key)
                if val and val != "null" and val != phone:
                    alts.append(Formatter.clean_phone(val))
            if alts:
                msg.append("📞 Alternate: " + ', '.join(alts[:3]))
            
            # Email
            email = record.get('Email', record.get('EmailID', ''))
            if email and email != "null":
                msg.append("📧 Email: " + email)
            
            # ========== 3. ADDRESS INFO ==========
            address = Formatter.clean_address(record.get('Adres', record.get('Address', '')))
            if address:
                msg.append("🏠 Address: " + address)
            else:
                msg.append("🏠 Address: Not Available")
            
            # ========== 4. SIM INFO ==========
            sim_info = Formatter.get_sim_info(record)
            if sim_info:
                msg.append("📡 SIM: " + sim_info)
            else:
                msg.append("📡 SIM: Not Available")
            
            # ========== 5. DOCUMENTS ==========
            doc = record.get('Aadhaar', record.get('DocumentNumber', ''))
            if doc and doc != "null":
                msg.append("🪪 Aadhaar: " + doc)
            else:
                msg.append("🪪 Aadhaar: ❌ Not Found")
            
            if idx < len(records):
                msg.append("")
                msg.append("━━━━━━━━━━━━━━━━━━━━━━━━")
        
        # Footer
        msg.append("")
        msg.append("━━━━━━━━━━━━━━━━━━━━━━━━")
        if tokens_info:
            if tokens_info.get('is_premium'):
                msg.append("💎 Premium User - Unlimited")
            else:
                msg.append("📊 Credits: " + str(tokens_info.get('tokens', 0)) + " left")
        msg.append("```")
        
        return '\n'.join(msg)