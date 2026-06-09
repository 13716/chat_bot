# from openai import OpenAI

# client = OpenAI(
#     api_key="sk-9da6d515e6cb46e18689ef58490566ba",
#     base_url="https://api.deepseek.com"
# )

# response = client.chat.completions.create(
#     model="deepseek-chat",
#     messages=[
#         {"role": "user", "content": "hello"}
#     ]
# )

# print(response.choices[0].message.content)
import pandas as pd
df_bank = pd.read_excel("test_bank_recon_T6_2026.xlsx", sheet_name="Sao kê ngân hàng")
df_book = pd.read_excel("test_bank_recon_T6_2026.xlsx", sheet_name="Sổ sách nội bộ")
df_bank.to_excel("bank.xlsx", index=False)
df_book.to_excel("book.xlsx", index=False)