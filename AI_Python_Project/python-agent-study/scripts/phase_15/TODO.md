_prepare_initial_state 中的rewrite节点的llm步骤没有记录到 langsmith的rag_agent_pipeline.run.query_rewrite节点

langsmith rag_agent_pipeline.run.decide_next_action 节点下面的多个llm节点都是默认名称，无法识别意图，因为plan相关的任务节点没有被langsmith追踪

测试脚本报错：
endpoint=/rag/chat
query> 你好
request_id=2815bc3ca1ff4f1a8d8ff91b80bb565a
trace_id=2815bc3ca1ff4f1a8d8ff91b80bb565a
effective_query=你好
answer:
你好，我是一个 RAG Agent 后端示例。当问题需要知识库信息时，我会执行检索、重排序、构造上下文并生成回答；如果只是问候、感谢或询问系统能力，我会直接回答。
source_count=0
query> 当前知识库中的战斗系统需求设计是什么？角色概念设计是什么？
Traceback (most recent call last):
  File "D:\AI_Agent_Project\AI_Python_Project\python-agent-study\scripts\phase_15\test_rag_agent_login_multiturn_cli.py", line 1341, in <module>
    raise SystemExit(main())
                     ^^^^^^
  File "D:\AI_Agent_Project\AI_Python_Project\python-agent-study\scripts\phase_15\test_rag_agent_login_multiturn_cli.py", line 1316, in main
    run_interactive_loop(
  File "D:\AI_Agent_Project\AI_Python_Project\python-agent-study\scripts\phase_15\test_rag_agent_login_multiturn_cli.py", line 997, in run_interactive_loop
    response = request_rag_chat(
               ^^^^^^^^^^^^^^^^^
  File "D:\AI_Agent_Project\AI_Python_Project\python-agent-study\scripts\phase_15\test_rag_agent_login_multiturn_cli.py", line 352, in request_rag_chat
    return post_json(
           ^^^^^^^^^^
  File "D:\AI_Agent_Project\AI_Python_Project\python-agent-study\scripts\phase_15\test_rag_agent_login_multiturn_cli.py", line 244, in post_json
    return send_json_request(request=request, timeout_seconds=timeout_seconds)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\AI_Agent_Project\AI_Python_Project\python-agent-study\scripts\phase_15\test_rag_agent_login_multiturn_cli.py", line 267, in send_json_request
    with urlopen(request, timeout=timeout_seconds) as response:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\TGG\AppData\Local\Programs\Python\Python312\Lib\urllib\request.py", line 215, in urlopen
    return opener.open(url, data, timeout)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\TGG\AppData\Local\Programs\Python\Python312\Lib\urllib\request.py", line 515, in open
    response = self._open(req, data)
               ^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\TGG\AppData\Local\Programs\Python\Python312\Lib\urllib\request.py", line 532, in _open
    result = self._call_chain(self.handle_open, protocol, protocol +
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\TGG\AppData\Local\Programs\Python\Python312\Lib\urllib\request.py", line 492, in _call_chain
    result = func(*args)
             ^^^^^^^^^^^
  File "C:\Users\TGG\AppData\Local\Programs\Python\Python312\Lib\urllib\request.py", line 1373, in http_open
    return self.do_open(http.client.HTTPConnection, req)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\TGG\AppData\Local\Programs\Python\Python312\Lib\urllib\request.py", line 1348, in do_open
    r = h.getresponse()
        ^^^^^^^^^^^^^^^
  File "C:\Users\TGG\AppData\Local\Programs\Python\Python312\Lib\http\client.py", line 1411, in getresponse
    response.begin()
  File "C:\Users\TGG\AppData\Local\Programs\Python\Python312\Lib\http\client.py", line 324, in begin
    version, status, reason = self._read_status()
                              ^^^^^^^^^^^^^^^^^^^
  File "C:\Users\TGG\AppData\Local\Programs\Python\Python312\Lib\http\client.py", line 285, in _read_status
    line = str(self.fp.readline(_MAXLINE + 1), "iso-8859-1")
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\TGG\AppData\Local\Programs\Python\Python312\Lib\socket.py", line 707, in readinto
    return self._sock.recv_into(b)
           ^^^^^^^^^^^^^^^^^^^^^^^
TimeoutError: timed out