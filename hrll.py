from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:20128/v1",
    api_key="sk-da0853597db97732-9414a4-3ce77926"
)

response = client.chat.completions.create(
    model="auto",
    messages=[{"role": "user", "content": "Hii, can you write me a code for palindrome in python?"}]
)

print(response.choices[0].message.content)