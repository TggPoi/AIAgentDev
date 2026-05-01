import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';
import { WebSocketServer } from 'ws';
import { TtsRelayService } from './speech/tts-relay.service';

async function bootstrap() {

  // 创建 Nest 应用，不能通过constructor构造函数获取 TtsRelayService 实例，因为 Nest 应用尚未完全初始化，此时依赖注入系统还未准备好
  const app = await NestFactory.create(AppModule);

  const ttsRelayService = app.get(TtsRelayService);
  const server = app.getHttpServer();

  //用于和前端进行 TTS 流式数据交互的 WebSocket 服务器，路径为 /speech/tts/ws
  //传输腾讯云TTS服务返回的音频数据流，实现前端的实时语音播放功能
  const ttsWss = new WebSocketServer({
    server,
    path: '/speech/tts/ws',
  });

  ttsWss.on('connection', (socket, request) => {
    const reqUrl = new URL(request.url ?? '', 'http://localhost');
    const wantedSessionId = reqUrl.searchParams.get('sessionId') ?? undefined;
    const sessionId = ttsRelayService.registerClient(socket, wantedSessionId);

    socket.on('close', () => {
      ttsRelayService.unregisterClient(sessionId);
    });
  });

  await app.listen(process.env.PORT ?? 3000);
}
bootstrap();