import { Inject, Injectable, NotFoundException } from '@nestjs/common';
import { EntityManager } from 'typeorm';
import { CreateBookDto } from './dto/create-book.dto';
import { UpdateBookDto } from './dto/update-book.dto';
import { Book } from './entities/book.entity';

@Injectable()
export class BookService {
  @Inject(EntityManager)
  private readonly entityManager: EntityManager;

  async create(createBookDto: CreateBookDto) {
    const book = this.entityManager.create(Book, {
      ...createBookDto,
      publishedAt: new Date(createBookDto.publishedAt),
    });
    return this.entityManager.save(Book, book);
  }

  async findAll() {
    return this.entityManager.find(Book, {
      order: { id: 'DESC' },
    });
  }

  async findOne(id: number) {
    const book = await this.entityManager.findOneBy(Book, { id });
    if (!book) {
      throw new NotFoundException(`Book #${id} not found`);
    }
    return book;
  }

  async update(id: number, updateBookDto: UpdateBookDto) {
    const book = await this.findOne(id);
    const { publishedAt, ...restPayload } = updateBookDto;
    const updatePayload: Partial<Book> = { ...restPayload };

    if (publishedAt !== undefined) {
      updatePayload.publishedAt = new Date(publishedAt);
    }

    const mergedBook = this.entityManager.merge(Book, book, updatePayload);
    return this.entityManager.save(Book, mergedBook);
  }

  async remove(id: number) {
    const book = await this.findOne(id);
    await this.entityManager.remove(Book, book);
    return { deleted: true };
  }
}