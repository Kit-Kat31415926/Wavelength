import { RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar, ResponsiveContainer } from 'recharts'

export default function TraitRadar({ traits, width = '340px', height = '280px', compact = false }) {
  if (!traits) return <div>Loading profile...</div>

  const labelMap = compact
    ? {
        Openness: 'Open',
        Conscientiousness: 'Consc.',
        Extraversion: 'Extra.',
        Agreeableness: 'Agree.',
        'Emotional Stability': 'Stable',
        'Novelty Seeking': 'Novelty',
        'Security Need': 'Security',
      }
    : null

  // Format trait data for Recharts
  const data = [
    { name: 'Openness', value: Math.round(traits.openness * 100) },
    { name: 'Conscientiousness', value: Math.round(traits.conscientiousness * 100) },
    { name: 'Extraversion', value: Math.round(traits.extraversion * 100) },
    { name: 'Agreeableness', value: Math.round(traits.agreeableness * 100) },
    { name: 'Emotional Stability', value: Math.round(traits.emotional_stability * 100) },
    { name: 'Novelty Seeking', value: Math.round(traits.novelty_seeking * 100) },
    { name: 'Security Need', value: Math.round(traits.security_need * 100) }
  ]

  return (
    <div
      style={{
        width,
        height,
        background: 'var(--bg2)',
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--border)',
        padding: compact ? '8px' : '16px',
        overflow: 'hidden'
      }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <RadarChart data={data} outerRadius={compact ? '58%' : '72%'}>
          <PolarGrid stroke="var(--border)" />
          <PolarAngleAxis 
            dataKey="name" 
            tickFormatter={(value) => (labelMap ? labelMap[value] || value : value)}
            tick={{ fill: 'var(--text2)', fontSize: compact ? 8 : 11 }} 
          />
          <Radar 
            name="Profile" 
            dataKey="value" 
            stroke="var(--gold)" 
            fill="var(--gold)" 
            fillOpacity={0.3} 
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  )
}
