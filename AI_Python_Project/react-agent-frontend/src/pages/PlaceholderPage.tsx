import { EmptyState } from '@/components/ui/PageState'
import styles from '@/pages/PlaceholderPage.module.css'

interface PlaceholderPageProps {
  description: string
  emptyDescription: string
  emptyTitle: string
  eyebrow: string
  title: string
}

export function PlaceholderPage({
  description,
  emptyDescription,
  emptyTitle,
  eyebrow,
  title,
}: PlaceholderPageProps) {
  return (
    <section aria-labelledby="placeholder-page-title">
      <header className={styles.header}>
        <p className={styles.eyebrow}>{eyebrow}</p>
        <h2 className={styles.title} id="placeholder-page-title">
          {title}
        </h2>
        <p className={styles.description}>{description}</p>
      </header>
      <EmptyState description={emptyDescription} title={emptyTitle} />
    </section>
  )
}
