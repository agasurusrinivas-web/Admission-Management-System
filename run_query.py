import os
import sys

# Change directory to inner project if needed
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from app import create_db_connection

def run_user_query():
    conn = create_db_connection()
    cur = conn.cursor(dictionary=True, buffered=True)
    
    query = """
    SELECT 
        application_number,
        student_name,
        JSON_UNQUOTE(JSON_EXTRACT(form_data, '$.advPhoto')) AS student_photo,
        JSON_UNQUOTE(JSON_EXTRACT(form_data, '$.father_photo')) AS father_photo,
        JSON_UNQUOTE(JSON_EXTRACT(form_data, '$.Communityfile')) AS community_certificate,
        JSON_UNQUOTE(JSON_EXTRACT(form_data, '$.parentSign')) AS parent_signature,
        JSON_UNQUOTE(JSON_EXTRACT(form_data, '$.accountsSign')) AS accounts_signature
    FROM applications
    WHERE form_data IS NOT NULL;
    """
    
    cur.execute(query)
    rows = cur.fetchall()
    
    print("\n" + "="*125)
    print(f"{'Application':<14} | {'Student Name':<15} | {'Student Photo':<45} | {'Parent Signature':<45}")
    print("="*125)
    
    for r in rows:
        app_no = str(r['application_number'] or '')
        name = str(r['student_name'] or '')
        photo = str(r['student_photo'] or 'null')
        if len(photo) > 42:
            photo = photo[:39] + "..."
        psign = str(r['parent_signature'] or 'null')
        if len(psign) > 42:
            psign = psign[:39] + "..."
            
        print(f"{app_no:<14} | {name:<15} | {photo:<45} | {psign:<45}")
    print("="*125 + "\n")
    
    # Also print full details for each record
    print("\n--- DETAILED DOCUMENTS & PHOTOS PER APPLICATION ---")
    for r in rows:
        print(f"\n[Application: {r['application_number']} - {r['student_name']}]")
        print(f"  * Student Photo        : {r['student_photo']}")
        print(f"  * Father Photo         : {r['father_photo']}")
        print(f"  * Community Certificate: {r['community_certificate']}")
        print(f"  * Parent Signature     : {r['parent_signature']}")
        print(f"  * Accounts Signature   : {r['accounts_signature']}")
    
    conn.close()

if __name__ == '__main__':
    run_user_query()
