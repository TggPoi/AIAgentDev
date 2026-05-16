def log_decorator(func):
    def wrapper():
        print("before")
        result = func()
        print("after")
        return result

    return wrapper

def chat() -> str:
    return "AI response"


decorated_chat = log_decorator(chat)

result = decorated_chat()
print(result)


#这种写法只能用于没有参数的函数
@log_decorator
def chat2() -> str:
    return "AI response"

#这里返回的就是wrapper函数，已经把chat函数包装到里面的func()
result = chat2()
print(result)


#带有参数的装饰器函数实现
def log_decorator2(func):
    #装饰器不知道将来要包装的函数长什么样子，所以使用*args和**kwargs来接受任意数量和类型的参数，接住所有参数，然后原样转发
    def wrapper(*args, **kwargs):
        print("before")
        result = func(*args, **kwargs)
        print("after")
        return result

    return wrapper


@log_decorator2
def chat3(message: str) -> str:
    return f"AI response for: {message}"


result = chat3("什么是 RAG？")
print(result)