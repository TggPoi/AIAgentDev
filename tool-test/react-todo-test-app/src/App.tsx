import { useState, useEffect } from 'react'
import './App.css'

interface Todo {
  id: number
  text: string
  completed: boolean
  category: 'work' | 'personal' | 'shopping'
}

type FilterType = 'all' | 'active' | 'completed'

function App() {
  const [todos, setTodos] = useState<Todo[]>(() => {
    const saved = localStorage.getItem('todos')
    return saved ? JSON.parse(saved) : []
  })
  const [inputValue, setInputValue] = useState('')
  const [category, setCategory] = useState<Todo['category']>('personal')
  const [filter, setFilter] = useState<FilterType>('all')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editValue, setEditValue] = useState('')

  useEffect(() => {
    localStorage.setItem('todos', JSON.stringify(todos))
  }, [todos])

  const addTodo = () => {
    if (inputValue.trim() === '') return
    const newTodo: Todo = {
      id: Date.now(),
      text: inputValue.trim(),
      completed: false,
      category
    }
    setTodos([...todos, newTodo])
    setInputValue('')
  }

  const deleteTodo = (id: number) => {
    setTodos(todos.filter(todo => todo.id !== id))
  }

  const toggleComplete = (id: number) => {
    setTodos(todos.map(todo =>
      todo.id === id ? { ...todo, completed: !todo.completed } : todo
    ))
  }

  const startEdit = (todo: Todo) => {
    setEditingId(todo.id)
    setEditValue(todo.text)
  }

  const saveEdit = (id: number) => {
    if (editValue.trim() === '') return
    setTodos(todos.map(todo =>
      todo.id === id ? { ...todo, text: editValue.trim() } : todo
    ))
    setEditingId(null)
    setEditValue('')
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditValue('')
  }

  const filteredTodos = todos.filter(todo => {
    if (filter === 'active') return !todo.completed
    if (filter === 'completed') return todo.completed
    return true
  })

  const stats = {
    total: todos.length,
    active: todos.filter(t => !t.completed).length,
    completed: todos.filter(t => t.completed).length
  }

  const getCategoryColor = (cat: string) => {
    switch (cat) {
      case 'work': return '#ff6b6b'
      case 'personal': return '#4ecdc4'
      case 'shopping': return '#ffe66d'
      default: return '#95a5a6'
    }
  }

  return (
    <div className="app">
      <div className="container">
        <h1>📝 Todo List</h1>
        
        <div className="stats">
          <div className="stat-item">
            <span className="stat-number">{stats.total}</span>
            <span className="stat-label">总计</span>
          </div>
          <div className="stat-item">
            <span className="stat-number">{stats.active}</span>
            <span className="stat-label">进行中</span>
          </div>
          <div className="stat-item">
            <span className="stat-number">{stats.completed}</span>
            <span className="stat-label">已完成</span>
          </div>
        </div>

        <div className="add-todo">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && addTodo()}
            placeholder="添加新任务..."
          />
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value as Todo['category'])}
          >
            <option value="work">工作</option>
            <option value="personal">个人</option>
            <option value="shopping">购物</option>
          </select>
          <button onClick={addTodo}>添加</button>
        </div>

        <div className="filters">
          <button
            className={filter === 'all' ? 'active' : ''}
            onClick={() => setFilter('all')}
          >
            全部
          </button>
          <button
            className={filter === 'active' ? 'active' : ''}
            onClick={() => setFilter('active')}
          >
            进行中
          </button>
          <button
            className={filter === 'completed' ? 'active' : ''}
            onClick={() => setFilter('completed')}
          >
            已完成
          </button>
        </div>

        <ul className="todo-list">
          {filteredTodos.map((todo) => (
            <li
              key={todo.id}
              className={`todo-item ${todo.completed ? 'completed' : ''} ${editingId === todo.id ? 'editing' : ''}`}
            >
              <div className="todo-content">
                <span
                  className="category-badge"
                  style={{ backgroundColor: getCategoryColor(todo.category) }}
                >
                  {todo.category === 'work' ? '工作' : todo.category === 'personal' ? '个人' : '购物'}
                </span>
                {editingId === todo.id ? (
                  <input
                    type="text"
                    value={editValue}
                    onChange={(e) => setEditValue(e.target.value)}
                    onKeyPress={(e) => e.key === 'Enter' && saveEdit(todo.id)}
                    onBlur={() => saveEdit(todo.id)}
                    autoFocus
                  />
                ) : (
                  <span
                    className="todo-text"
                    onClick={() => toggleComplete(todo.id)}
                  >
                    {todo.text}
                  </span>
                )}
              </div>
              <div className="todo-actions">
                {editingId === todo.id ? (
                  <button className="btn-save" onClick={() => saveEdit(todo.id)}>
                    保存
                  </button>
                ) : (
                  <button className="btn-edit" onClick={() => startEdit(todo)}>
                    编辑
                  </button>
                )}
                <button className="btn-delete" onClick={() => deleteTodo(todo.id)}>
                  删除
                </button>
              </div>
            </li>
          ))}
        </ul>

        {filteredTodos.length === 0 && (
          <p className="empty-message">暂无任务，添加一个开始吧！</p>
        )}
      </div>
    </div>
  )
}

export default App
