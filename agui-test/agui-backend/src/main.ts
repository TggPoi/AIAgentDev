import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';

async function bootstrap() {
  const app = await NestFactory.create(AppModule);

  // 允许跨域请求，特别是前端开发时，前端服务器和后端服务器通常不在同一个域上，这时候就需要开启 CORS 来允许跨域请求。
  app.enableCors({
    origin: '*',
    credentials: true,
  });
  await app.listen(process.env.PORT ?? 3000);
}
bootstrap();