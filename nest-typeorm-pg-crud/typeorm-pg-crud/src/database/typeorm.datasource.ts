import 'dotenv/config';
import { DataSource } from 'typeorm';
import { Conversation } from '../conversations/entities/conversation.entity';
import { Message } from '../conversations/entities/message.entity';
import { User } from '../conversations/entities/user.entity';
import { AgentRun } from '../learning/entities/agent-run.entity';
import { AgentTask } from '../learning/entities/agent-task.entity';
import { CreateLearningAgentTables1760000000000 } from '../migrations/1760000000000-CreateLearningAgentTables';

export default new DataSource({
  type: 'postgres',
  host: process.env.DATABASE_HOST ?? 'localhost',
  port: Number.parseInt(process.env.DATABASE_PORT ?? '5432', 10),
  username: process.env.DATABASE_USERNAME ?? 'user',
  password: process.env.DATABASE_PASSWORD ?? '123456',
  database: process.env.DATABASE_NAME ?? 'hello_pg',
  entities: [User, Conversation, Message, AgentTask, AgentRun],
  migrations: [CreateLearningAgentTables1760000000000],
  synchronize: false,
});
