import os
from dotenv import load_dotenv
load_dotenv()

from app.models.superadmin import SuperAdmin

email = "albinjegus10@gmail.com"
password = "ajab1234@#J"
name = "Super Admin"

existing = SuperAdmin.get_by_email(email)
if existing:
    print(f"Superadmin {email} already exists.")
else:
    sa_id = SuperAdmin.create(name=name, email=email, password=password)
    print(f"Superadmin {email} created successfully with ID {sa_id}.")
