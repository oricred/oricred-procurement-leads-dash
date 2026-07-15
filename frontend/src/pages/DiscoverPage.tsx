import { NavLink, useSearchParams } from 'react-router-dom';
import AwardsPage from './AwardsPage';
import TendersPage from './TendersPage';
import PastDuePage from './PastDuePage';
import HistoricalContactsPage from './HistoricalContactsPage';

const tabs = [['awards', 'Awards'], ['tenders', 'Tenders'], ['past-due', 'Past Due'], ['history', 'Supplier History']] as const;
export default function DiscoverPage() {
  const [params] = useSearchParams(); const tab = tabs.some(([v]) => v === params.get('tab')) ? params.get('tab')! : 'awards';
  const content = tab === 'tenders' ? <TendersPage /> : tab === 'past-due' ? <PastDuePage /> : tab === 'history' ? <HistoricalContactsPage /> : <AwardsPage />;
  return <div className="h-full"><div className="flex gap-1 border-b border-surface-300 mb-5 overflow-x-auto">{tabs.map(([value, label]) => <NavLink key={value} to={`/discover?tab=${value}`} className={() => `px-3 py-2 text-sm whitespace-nowrap border-b-2 ${tab === value ? 'border-primary-400 text-primary-400' : 'border-transparent text-gray-500 hover:text-gray-200'}`}>{label}</NavLink>)}</div>{content}</div>;
}