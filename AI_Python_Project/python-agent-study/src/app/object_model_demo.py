def demo_assignment() -> None:
    print("=== demo_assignment ===")

    a = [1, 2, 3]
    b = a

    print("before:")
    print("a =", a)
    print("b =", b)
    print("a is b =", a is b)

    b.append(4)

    print("after:")
    print("a =", a)
    print("b =", b)
    print("a is b =", a is b)


def demo_copy() -> None:
    print("=== demo_copy ===")

    a = [1, 2, 3]
    b = a.copy()

    print("before:")
    print("a =", a)
    print("b =", b)
    print("a is b =", a is b)

    b.append(4)

    print("after:")
    print("a =", a)
    print("b =", b)
    print("a is b =", a is b)


def demo_function_param() -> None:
    print("=== demo_function_param ===")

    def add_item(items: list[str]) -> None:
        items.append("new")

    values = ["old"]
    add_item(values)

    print("values =", values)


def demo_default_param_wrong(message: str, messages: list[str] = []) -> list[str]:
    messages.append(message)
    return messages


def demo_default_param_right(
    message: str,
    messages: list[str] | None = None,
) -> list[str]:
    if messages is None:
        messages = []

    messages.append(message)
    return messages


def main() -> None:
    demo_assignment()
    print()

    demo_copy()
    print()

    demo_function_param()
    print()

    print("=== demo_default_param_wrong ===")
    print(demo_default_param_wrong("hello"))
    print(demo_default_param_wrong("world"))
    print(demo_default_param_wrong("again"))
    print()

    print("=== demo_default_param_right ===")
    print(demo_default_param_right("hello"))
    print(demo_default_param_right("world"))
    print(demo_default_param_right("again"))


if __name__ == "__main__":
    main()


##
# (.venv) PS D:\AI_Agent_Project\AI_Python_Project\python-agent-study> python -m app.object_model_demo
# === demo_assignment ===
# before:
# a = [1, 2, 3]
# b = [1, 2, 3]
# a is b = True
# after:
# a = [1, 2, 3, 4]
# b = [1, 2, 3, 4]
# a is b = True

# === demo_copy ===
# before:
# a = [1, 2, 3]
# b = [1, 2, 3]
# a is b = False
# after:
# a = [1, 2, 3]
# b = [1, 2, 3, 4]
# a is b = False

# === demo_function_param ===
# values = ['old', 'new']

# === demo_default_param_wrong ===
# ['hello']
# ['hello', 'world']
# ['hello', 'world', 'again']

# === demo_default_param_right ===
# ['hello']
# ['world']
# ['again']
# #