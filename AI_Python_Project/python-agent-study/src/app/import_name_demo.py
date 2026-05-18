import app.name_demo


def main() -> None:
    print("import_name_demo is running")


if __name__ == "__main__":
    main()

# `name_demo` 被 import 时，顶部的 `print` 会执行，但 `main()` 不会执行。
# (.venv) PS D:\AI_Agent_Project\AI_Python_Project\python-agent-study> python -m app.import_name_demo
# module name is: app.name_demo
# import_name_demo is running