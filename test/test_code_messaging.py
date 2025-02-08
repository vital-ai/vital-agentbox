import asyncio
from agentbox.box.code_exec_box import CodeExecutorBox

async def main():
    code_box = CodeExecutorBox()

    # A flat code snippet that uses the injected messaging API.
    # It awaits the messaging.send call and prints its reply,
    # then performs a vowel count.
    code = r'''
reply = await messaging.send({"greeting": "Hello, host!", "data": "Test message"})
print("Reply from host:", reply)

sentence = "how many vowels are in this exact sentence?"
vowels = "aeiouAEIOU"
count = 0
for char in sentence:
    if char in vowels:
        count += 1
print(f"Vowel Count: {count}")
'''

    # Run the code in Pyodide and get the result.
    result = await code_box.run_python_with_pyodide(code)
    if result['success']:
        print("Output from Pyodide:")
        print(result['output'])
    else:
        print("Error in Pyodide:", result['error'])

if __name__ == "__main__":
    asyncio.run(main())
