from dotenv import load_dotenv
load_dotenv()
from app.models.superadmin import SuperAdmin
from app.utils.auth import verify_password

email = 'albinjegus10@gmail.com'
password = 'ajab1234@#J'

sa = SuperAdmin.get_by_email(email)
if not sa:
    print('User not found.')
else:
    print('User found!')
    print('Password stored: ' + str(sa['password']))
    is_valid = verify_password(password, sa['password'])
    print('Password valid: ' + str(is_valid))
