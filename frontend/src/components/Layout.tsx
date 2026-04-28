import { NavLink } from 'react-router-dom'
import { Search, FlaskConical, Database, MessageCircle, Atom } from 'lucide-react'
import { clsx } from 'clsx'

const NAV = [
  { to: '/discover',   icon: Search,        label: 'Discover'   },
  { to: '/extract',    icon: FlaskConical,  label: 'Extract'    },
  { to: '/database',   icon: Database,      label: 'Database'   },
  { to: '/ask',        icon: MessageCircle, label: 'Ask'        },
]

export function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen bg-bg overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 flex-shrink-0 border-r border-border flex flex-col">
        {/* Logo */}
        <div className="h-14 flex items-center gap-3 px-4 border-b border-border">
          <div className="w-7 h-7 bg-primary rounded-lg flex items-center justify-center">
            <Atom size={16} className="text-white" />
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-100">MOF Discovery</div>
            <div className="text-[10px] text-muted uppercase tracking-widest">AI Scientist</div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 p-2 space-y-0.5">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink key={to} to={to}
              className={({ isActive }) => clsx(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all',
                isActive
                  ? 'bg-primary/15 text-cyan-200'
                  : 'text-muted hover:text-slate-200 hover:bg-border'
              )}
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Footer */}
        <div className="p-4 border-t border-border">
          <div className="text-[10px] text-muted leading-relaxed">
            GPT-4o · RAG · CoRE MOF<br/>
            Semantic Scholar · PubMed · OpenAlex
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-auto">
        {children}
      </main>
    </div>
  )
}
