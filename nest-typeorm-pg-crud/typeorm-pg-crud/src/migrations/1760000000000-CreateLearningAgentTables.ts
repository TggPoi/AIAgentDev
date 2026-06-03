import { MigrationInterface, QueryRunner } from 'typeorm';

export class CreateLearningAgentTables1760000000000 implements MigrationInterface {
  name = 'CreateLearningAgentTables1760000000000';

  public async up(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`
      CREATE TYPE "public"."learning_agent_tasks_status_enum"
      AS ENUM ('queued', 'running', 'succeeded', 'failed')
    `);
    await queryRunner.query(`
      CREATE TYPE "public"."learning_agent_runs_status_enum"
      AS ENUM ('running', 'succeeded', 'failed')
    `);
    await queryRunner.query(`
      CREATE TABLE "learning_agent_tasks" (
        "id" uuid NOT NULL DEFAULT gen_random_uuid(),
        "external_key" text NOT NULL,
        "title" text NOT NULL,
        "description" text,
        "metadata" jsonb NOT NULL DEFAULT '{}'::jsonb,
        "status" "public"."learning_agent_tasks_status_enum"
          NOT NULL DEFAULT 'queued',
        "attempt_count" integer NOT NULL DEFAULT 0,
        "available_at" TIMESTAMP WITH TIME ZONE
          NOT NULL DEFAULT CURRENT_TIMESTAMP,
        "locked_at" TIMESTAMP WITH TIME ZONE,
        "locked_by" text,
        "version" integer NOT NULL DEFAULT 1,
        "created_at" TIMESTAMP WITH TIME ZONE
          NOT NULL DEFAULT now(),
        "updated_at" TIMESTAMP WITH TIME ZONE
          NOT NULL DEFAULT now(),
        CONSTRAINT "UQ_learning_agent_tasks_external_key"
          UNIQUE ("external_key"),
        CONSTRAINT "PK_learning_agent_tasks"
          PRIMARY KEY ("id")
      )
    `);
    await queryRunner.query(`
      CREATE TABLE "learning_agent_runs" (
        "id" uuid NOT NULL DEFAULT gen_random_uuid(),
        "task_id" uuid NOT NULL,
        "status" "public"."learning_agent_runs_status_enum"
          NOT NULL DEFAULT 'running',
        "input" jsonb NOT NULL DEFAULT '{}'::jsonb,
        "output" jsonb,
        "error_message" text,
        "created_at" TIMESTAMP WITH TIME ZONE
          NOT NULL DEFAULT now(),
        "updated_at" TIMESTAMP WITH TIME ZONE
          NOT NULL DEFAULT now(),
        CONSTRAINT "PK_learning_agent_runs"
          PRIMARY KEY ("id"),
        CONSTRAINT "FK_learning_agent_runs_task"
          FOREIGN KEY ("task_id")
          REFERENCES "learning_agent_tasks"("id")
          ON DELETE CASCADE
      )
    `);
    await queryRunner.query(`
      CREATE INDEX "idx_learning_agent_tasks_status_available"
      ON "learning_agent_tasks" ("status", "available_at")
    `);
    await queryRunner.query(`
      CREATE INDEX "idx_learning_agent_tasks_queued_available"
      ON "learning_agent_tasks" ("available_at", "id")
      WHERE "status" = 'queued'
    `);
    await queryRunner.query(`
      CREATE INDEX "idx_learning_agent_runs_task_created"
      ON "learning_agent_runs" ("task_id", "created_at")
    `);
  }

  public async down(queryRunner: QueryRunner): Promise<void> {
    await queryRunner.query(`DROP TABLE "learning_agent_runs"`);
    await queryRunner.query(`DROP TABLE "learning_agent_tasks"`);
    await queryRunner.query(
      `DROP TYPE "public"."learning_agent_runs_status_enum"`,
    );
    await queryRunner.query(
      `DROP TYPE "public"."learning_agent_tasks_status_enum"`,
    );
  }
}
