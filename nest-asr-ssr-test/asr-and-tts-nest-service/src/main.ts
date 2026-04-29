import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';
import { WebSocketServer } from 'ws';
import { TtsRelayService } from './speech/tts-relay.service';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  const ttsRelayService = app.get(TtsRelayService);
  const server = app.getHttpServer();

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