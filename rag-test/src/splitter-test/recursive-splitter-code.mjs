import "dotenv/config";
import "cheerio";
import { Document } from "@langchain/core/documents";
import { RecursiveCharacterTextSplitter } from "@langchain/textsplitters";

const jsCode = `// Complete shopping cart implementation
class Product {
  constructor(id, name, price, description) {
    this.id = id;
    this.name = name;
    this.price = price;
    this.description = description;
  }

  getFormattedPrice() {
    return '$' + this.price.toFixed(2);
  }
}

class ShoppingCart {
  constructor() {
    this.items = [];
    this.discountCode = null;
    this.taxRate = 0.08;
  }

  addItem(product, quantity = 1) {
    const existingItem = this.items.find(item => item.product.id === product.id);
    if (existingItem) {
      existingItem.quantity += quantity;
    } else {
      this.items.push({ product, quantity, addedAt: new Date() });
    }
    return this;
  }

  removeItem(productId) {
    this.items = this.items.filter(item => item.product.id !== productId);
    return this;
  }

  calculateSubtotal() {
    return this.items.reduce((total, item) => {
      return total + (item.product.price * item.quantity);
    }, 0);
  }

  calculateTotal() {
    const subtotal = this.calculateSubtotal();
    const discount = this.calculateDiscount();
    const tax = (subtotal - discount) * this.taxRate;
    return subtotal - discount + tax;
  }

  calculateDiscount() {
    if (!this.discountCode) return 0;
    const discounts = { 'SAVE10': 0.10, 'SAVE20': 0.20, 'WELCOME': 0.15 };
    return this.calculateSubtotal() * (discounts[this.discountCode] || 0);
  }
}

// Usage example
const product1 = new Product(1, 'Laptop', 999.99, 'High-performance laptop');
const product2 = new Product(2, 'Mouse', 29.99, 'Wireless mouse');
const cart = new ShoppingCart();
cart.addItem(product1, 1).addItem(product2, 2);
console.log('Total:', cart.calculateTotal());`;

const jsCodeDoc = new Document({
    pageContent: jsCode
});

//指定语言，就会按照对应的语法来分割。支持的语言有很多，包括： java、go、js、html、python、rust、swift、markdown 等
const codeSplitter = RecursiveCharacterTextSplitter.fromLanguage('js', {
    chunkSize: 300,
    chunkOverlap: 60,
})

const splitDocuments = await codeSplitter.splitDocuments([jsCodeDoc]);

// console.log(splitDocuments);

splitDocuments.forEach(document => {
    console.log(document);
    console.log('charater length:',document.pageContent.length);
});

/** 测试结果：按照 js 语言的语法来分割，优先保证语义完整，宁愿 chunk 小一点，也不愿意在一个函数或者类中间切断。比如第一个 chunk 包含了 Product 类的定义，第二个 chunk 包含了 ShoppingCart 类的定义，第三个 chunk 包含了使用示例的代码。每个 chunk 的字符数都没有超过 300，因为 splitter 在分割时会尽量保持每个函数或者类的完整性，而不是简单地按照字符数来切割。
 * 
 * PS D:\AI_Agent_Project\rag-test> node .\src\splitter-test\recursive-splitter-code.mjs
Document {
  pageContent: '// Complete shopping cart implementation\n' +
    'class Product {\n' +
    '  constructor(id, name, price, description) {\n' +
    '    this.id = id;\n' +
    '    this.name = name;\n' +
    '    this.price = price;\n' +
    '    this.description = description;\n' +
    '  }\n' +
    '\n' +
    '  getFormattedPrice() {\n' +
    "    return '$' + this.price.toFixed(2);\n" +
    '  }\n' +
    '}',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 277
Document {
  pageContent: 'class ShoppingCart {\n' +
    '  constructor() {\n' +
    '    this.items = [];\n' +
    '    this.discountCode = null;\n' +
    '    this.taxRate = 0.08;\n' +
    '  }',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 118
Document {
  pageContent: 'addItem(product, quantity = 1) {\n' +
    '    const existingItem = this.items.find(item => item.product.id === product.id);\n' +
    '    if (existingItem) {\n' +
    '      existingItem.quantity += quantity;\n' +
    '    } else {\n' +
    '      this.items.push({ product, quantity, addedAt: new Date() });\n' +
    '    }\n' +
    '    return this;\n' +
    '  }',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 286
Document {
  pageContent: 'removeItem(productId) {\n' +
    '    this.items = this.items.filter(item => item.product.id !== productId);\n' +
    '    return this;\n' +
    '  }\n' +
    '\n' +
    '  calculateSubtotal() {\n' +
    '    return this.items.reduce((total, item) => {\n' +
    '      return total + (item.product.price * item.quantity);\n' +
    '    }, 0);\n' +
    '  }',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 266
Document {
  pageContent: 'calculateTotal() {\n' +
    '    const subtotal = this.calculateSubtotal();\n' +
    '    const discount = this.calculateDiscount();\n' +
    '    const tax = (subtotal - discount) * this.taxRate;\n' +
    '    return subtotal - discount + tax;\n' +
    '  }',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 208
Document {
  pageContent: 'calculateDiscount() {\n' +
    '    if (!this.discountCode) return 0;\n' +
    "    const discounts = { 'SAVE10': 0.10, 'SAVE20': 0.20, 'WELCOME': 0.15 };\n" +
    '    return this.calculateSubtotal() * (discounts[this.discountCode] || 0);\n' +
    '  }\n' +
    '}\n' +
    '\n' +
    '// Usage example',
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 233
Document {
  pageContent: "const product1 = new Product(1, 'Laptop', 999.99, 'High-performance laptop');\n" +
    "const product2 = new Product(2, 'Mouse', 29.99, 'Wireless mouse');\n" +
    'const cart = new ShoppingCart();\n' +
    'cart.addItem(product1, 1).addItem(product2, 2);\n' +
    "console.log('Total:', cart.calculateTotal());",
  metadata: { loc: { lines: [Object] } },
  id: undefined
}
charater length: 271
 */