import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
})

export const metadata: Metadata = {
  title: 'Compose - Create short-form videos in seconds',
  description: 'Upload a clip. Describe the vibe. Export.',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="font-sans tracking-tight-body bg-radial-dark min-h-screen">
        <div className="noise-overlay" />
        {children}
      </body>
    </html>
  )
}
