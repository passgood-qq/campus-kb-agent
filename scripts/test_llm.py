import os
from dotenv import load_dotenv
from openai import OpenAI

# 加载 .env 环境变量
load_dotenv()

# 初始化 LLM 客户端
client = OpenAI(
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL")
)

def test_single_chat():
    response = client.chat.completions.create(
        model=os.getenv("LLM_MODEL"),
        messages=[
            {"role": "user", "content": "你好，请用一句话介绍你自己"}
        ],
        temperature=0.7
    )
    print("AI 回复：", response.choices[0].message.content)
    print("\n✅ 调用成功，总 token 消耗：", response.usage.total_tokens)

if __name__ == "__main__":
    test_single_chat()
