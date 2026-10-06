-- Select Database
USE project_db;

-- Query to Extract Photos, Documents, and Signatures from Applications
SELECT 
    application_number,
    student_name,
    -- Student Photo
    JSON_UNQUOTE(JSON_EXTRACT(form_data, '$.advPhoto')) AS student_photo,
    
    -- Father Photo
    JSON_UNQUOTE(JSON_EXTRACT(form_data, '$.father_photo')) AS father_photo,
    
    -- Community Certificate / Marksheet
    JSON_UNQUOTE(JSON_EXTRACT(form_data, '$.Communityfile')) AS community_certificate,
    
    -- Parent Signature
    JSON_UNQUOTE(JSON_EXTRACT(form_data, '$.parentSign')) AS parent_signature,
    
    -- Accounts Signature
    JSON_UNQUOTE(JSON_EXTRACT(form_data, '$.accountsSign')) AS accounts_signature
FROM applications
WHERE form_data IS NOT NULL;
