import { NavLink, useSearchParams } from 'react-router-dom';
import { BarChart3 } from 'lucide-react';
import AwardsPage from './AwardsPage';
import TendersPage from './TendersPage';
import PastDuePage from './PastDuePage';
import HistoricalContactsPage from './HistoricalContactsPage';
import MatchingPage from './MatchingPage';
import StatsPage from './StatsPage';
import HelpLink from '../components/HelpLink';

const tabs = [['stats', 'Statistics'], ['awards', 'Awards'], ['tenders', 'Tenders'], ['watching', 'Watching'], ['past-due', 'Past Due'], ['history', 'Supplier History']] as const;
export default function DiscoverPage() {
  const [params] = useSearchParams(); const tab = tabs.some(([v]) => v === params.get('tab')) ? params.get('tab')! : 'stats';
  const content = tab === 'tenders' ? <TendersPage /> : tab === 'watching' ? <MatchingPage /> : tab === 'stats' ? <StatsPage /> : tab === 'past-due' ? <PastDuePage /> : tab === 'history' ? <HistoricalContactsPage /> : <AwardsPage />;
  return <div className="h-full"><div className="flex items-center gap-1 border-b border-surface-300 mb-5 overflow-x-auto"><div className="flex gap-1">{tabs.map(([value, label]) => <NavLink key={value} to={`/discover?tab=${value}`} className={() => `px-3 py-2 text-sm whitespace-nowrap border-b-2 ${tab === value ? 'border-primary-400 text-primary-400' : 'border-transparent text-gray-500 hover:text-gray-200'}`}>{value === 'stats' ? <span className="flex items-center gap-1.5"><BarChart3 className="w-3.5 h-3.5" />{label}</span> : label}</NavLink>)}</div><div className="ml-auto pl-3 shrink-0"><HelpLink section="discover" /></div></div>{content}</div>;
}
