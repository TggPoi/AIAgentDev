import { Module } from '@nestjs/common';
import { BookService } from './book.service';
import { BookController } from './book.controller';

@Module({
  controllers: [BookController],
  providers: [//提供可注入的类
    BookService,
    //自定义测试用的provider，模拟一个简单的书籍仓库
    {
      provide: 'BOOK_REPOSITORY',
      useFactory() {
        // 定义一个对象数组，内存 mock 仓库，适合测试，无需外部依赖
        const books: { id: number; title: string }[] = [
          { id: 1, title: 'Book 1' },
          { id: 2, title: 'Book 2' },
          { id: 3, title: 'Book 3' },
        ];
        //返回一个对象，包含一个 findAll 方法，返回所有书籍
        return {
          findAll: () => [...books]
        };
      },
    },
  ],
})

export class BookModule {}
