import { registerAs } from '@nestjs/config';

export default registerAs('database', () => ({
  type: 'postgres' as const,
  host: process.env.DATABASE_HOST ?? 'localhost',
  port: Number.parseInt(process.env.DATABASE_PORT ?? '5432', 10),
  username: process.env.DATABASE_USERNAME ?? 'user',
  password: process.env.DATABASE_PASSWORD ?? '123456',
  database: process.env.DATABASE_NAME ?? 'hello_pg',
  synchronize: (process.env.DATABASE_SYNCHRONIZE ?? 'true') === 'true',
  logging: (process.env.DATABASE_LOGGING ?? 'true') === 'true',
}));
