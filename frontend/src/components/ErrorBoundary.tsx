import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Icon } from './icons'

interface Props {
  children: ReactNode
}
interface State {
  error: Error | null
}

// Catches render-time crashes (e.g. a malformed state payload) so one bad
// region shows a friendly error + retry instead of white-screening the whole
// app.
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('UI crashed:', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="h-full flex items-center justify-center bg-ink-50 p-6">
          <div className="max-w-md text-center">
            <div className="flex justify-center mb-3 text-rose-500"><Icon name="alertTriangle" className="w-10 h-10" /></div>
            <h2 className="text-lg font-bold text-ink-900">Something went wrong</h2>
            <p className="text-sm text-ink-500 mt-1 mb-4">
              The {''}view hit an unexpected error. Your data is safe — try reloading.
            </p>
            <pre className="text-left text-xs text-rose-700 bg-rose-50 border border-rose-100 rounded-lg p-3 mb-4 overflow-auto max-h-40">
              {String(this.state.error)}
            </pre>
            <button className="btn-primary" onClick={() => window.location.reload()}>
              Reload app
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
