from hl import Api, Account
import os
from dotenv import load_dotenv
load_dotenv()

account = Account(
    address=os.environ["HL_ADDRESS_1"],
    secret_key=os.environ["HL_SECRET_KEY_1"]
)
api = Api.create(account=account)
print(dir(api.exchange))