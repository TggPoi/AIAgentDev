const http = require('http');

http.get('http://localhost:3000/events', (res) => {
  console.log('statusCode:', res.statusCode);
  console.log('headers:', res.headers);
  console.log('--- 开始接收原始 HTTP 流 ---\n');

  // 1. 用来存放“还没组成完整 SSE 事件”的文本
  let buffer = '';

  // 2. 每当网络层收到一段响应体数据，就会触发 data 事件
  res.on('data', (chunk) => {
    // chunk 先是 Buffer，需要转成字符串
    const text = chunk.toString('utf8');

    console.log('【收到原始 chunk】');
    console.log(JSON.stringify(text));
    console.log('');

    // 3. 追加到缓冲区
    buffer += text;

    // 4. SSE 事件是用 \n\n 分隔的
    // 只要 buffer 里还包含完整事件，就持续切出来处理
    let boundaryIndex;
    while ((boundaryIndex = buffer.indexOf('\n\n')) !== -1) {
      // 取出一条完整 SSE 事件文本
      const rawEvent = buffer.slice(0, boundaryIndex);

      // 从缓冲区移除这条已经处理过的事件
      buffer = buffer.slice(boundaryIndex + 2);

      if (!rawEvent.trim()) {
        continue;
      }

      console.log('【切出一条完整 SSE 事件】');
      console.log(JSON.stringify(rawEvent));
      console.log('');

      // 5. 逐行解析 SSE 字段
      const lines = rawEvent.split('\n');

      let dataLines = [];

      for (const line of lines) {
        if (line.startsWith('data:')) {
          // 去掉 "data:" 前缀，并 trim 掉前导空格
          const value = line.slice(5).trimStart();
          dataLines.push(value);
        }
      }

      // 6. 根据 SSE 规则，多行 data 要拼起来
      const dataText = dataLines.join('\n');

      console.log('【解析出的 data 字段】');
      console.log(dataText);
      console.log('');

      // 7. 判断结束标记
      if (dataText === '[DONE]') {
        console.log('✅ 收到结束标记 [DONE]');
        continue;
      }

      // 8. 如果 data 是 JSON，就尝试解析
      try {
        const obj = JSON.parse(dataText);
        console.log('【解析后的 JSON 对象】');
        console.log(obj);
        console.log('');
      } catch (err) {
        console.log('【data 不是 JSON，按纯文本处理】');
        console.log(dataText);
        console.log('');
      }
    }
  });

  res.on('end', () => {
    console.log('--- HTTP 响应流结束 ---');
  });

  res.on('error', (err) => {
    console.error('响应流错误:', err);
  });
}).on('error', (err) => {
  console.error('请求错误:', err);
});