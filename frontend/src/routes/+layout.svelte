<script lang="ts">
	// @ts-ignore
	import '../app.css';
	// @ts-ignore
	import { page } from '$app/stores';
	import {
		LayoutDashboard,
		Library,
		FolderTree,
		History,
		Settings,
		Database,
		CassetteTape,
		Activity,
		ChevronLeft,
		ChevronRight,
		PieChart
	} from 'lucide-svelte';
	import { cn } from '$lib/utils';
	import { Toaster } from 'svelte-sonner';
	import ScanStatusOverlay from '$lib/components/ScanStatusOverlay.svelte';
	import { client } from '$lib/api/client.gen';

	let { children } = $props();

	// Initialize API client configuration
	const apiUrl = (import.meta as any).env?.VITE_API_URL || '';
	client.setConfig({ baseUrl: apiUrl });

	const navItems = [
		{ name: 'Overview', href: '/', icon: LayoutDashboard },
		{ name: 'Insights', href: '/insights', icon: PieChart },
		{ name: 'Archive Index', href: '/index-browser', icon: Library },
		{ name: 'Filesystem', href: '/filesystem', icon: FolderTree },
		{ name: 'Jobs', href: '/jobs', icon: Activity },
		{ name: 'Media Inventory', href: '/inventory', icon: CassetteTape },
		{ name: 'Data Recovery', href: '/restores', icon: History }
	];

	let isSidebarOpen = $state(true);
	let showShortcuts = $state(false);

	function handleGlobalKeyDown(e: KeyboardEvent) {
		if (e.key === '?' && !['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) {
			showShortcuts = !showShortcuts;
		}
		if (showShortcuts && e.key === 'Escape') {
			showShortcuts = false;
		}

		// Navigation Shortcuts (Single keys only, no modifiers)
		if (!['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName) && !e.ctrlKey && !e.metaKey && !e.altKey) {
			if (e.key === 'd') window.location.href = '/';
			if (e.key === 'g') window.location.href = '/insights';
			if (e.key === 'i') window.location.href = '/index-browser';
			if (e.key === 't') window.location.href = '/filesystem';
			if (e.key === 'a') window.location.href = '/jobs';
			if (e.key === 'm') window.location.href = '/inventory';
			if (e.key === 'r') window.location.href = '/restores';
			if (e.key === 's') window.location.href = '/settings';
		}
	}
</script>

<svelte:window onkeydown={handleGlobalKeyDown} />

<Toaster theme="dark" richColors position="top-center" closeButton />

<div class="flex h-screen bg-background text-foreground overflow-hidden font-sans antialiased selection:bg-blue-500/30">
	<!-- Sidebar -->
	<aside
		class={cn(
			"bg-bg-secondary border-r border-border-color flex flex-col transition-all duration-500 ease-[cubic-bezier(0.4,0,0.2,1)] relative z-[1000] shadow-2xl",
			isSidebarOpen ? "w-64" : "w-20"
		)}
	>
		<!-- Logo Section -->
		<div class="h-20 flex items-center px-6 shrink-0 relative overflow-hidden border-b border-white/[0.03]">
			<div class="absolute inset-0 bg-gradient-to-br from-blue-600/5 to-transparent"></div>
			<div class="flex items-center gap-3 relative z-10">
				<div class="w-9 h-9 bg-blue-600 flex items-center justify-center rounded-xl shadow-lg shadow-blue-600/20 group-hover:scale-110 transition-transform duration-500">
					<Database class="text-white" size={20} />
				</div>
				{#if isSidebarOpen}
					<div class="flex flex-col animate-in fade-in slide-in-from-left-2 duration-500">
						<span class="text-lg font-bold leading-none">TapeHoard</span>
						<span class="text-6xs font-medium text-blue-400 uppercase tracking-wider mt-1">Backup Manager</span>
					</div>
				{/if}
			</div>
		</div>

		<!-- Nav Links -->
		<nav class="flex-1 overflow-y-auto px-4 py-6 space-y-1 scrollbar-hide">
			{#each navItems as item}
				<a
					href={item.href}
					class={cn(
						"flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-300 group relative",
						$page.url.pathname === item.href
							? "bg-blue-600 text-white shadow-xl shadow-blue-600/20"
							: "text-text-secondary hover:bg-white/5 hover:text-text-primary"
					)}
				>
					<item.icon size={18} class={cn("transition-transform duration-300 group-hover:scale-110", $page.url.pathname === item.href ? "text-white" : "opacity-60 group-hover:opacity-100")} />
					{#if isSidebarOpen}
						<span class="text-xs font-semibold animate-in fade-in slide-in-from-left-2 duration-300">
							{item.name}
						</span>
					{/if}

					{#if $page.url.pathname === item.href}
						<div class="absolute right-0 top-1/2 -translate-y-1/2 w-1 h-5 bg-white rounded-l-full"></div>
					{/if}
				</a>
			{/each}
		</nav>

		<!-- Bottom Actions -->
		<div class="p-4 space-y-1 border-t border-white/[0.03] bg-black/10">
			<a
				href="/settings"
				class={cn(
					"flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-300 group",
					$page.url.pathname === '/settings'
						? "bg-bg-tertiary text-text-primary border border-white/10"
						: "text-text-secondary hover:bg-white/5 hover:text-text-primary"
				)}
			>
				<Settings size={18} class="opacity-60 group-hover:opacity-100" />
				{#if isSidebarOpen}
					<span class="text-xs font-semibold">Settings</span>
				{/if}
			</a>
			<button
				class="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-text-secondary hover:bg-white/5 hover:text-text-primary transition-all group"
				onclick={() => isSidebarOpen = !isSidebarOpen}
			>
				{#if isSidebarOpen}
					<ChevronLeft size={18} class="opacity-60 group-hover:opacity-100" />
					<span class="text-xs font-semibold">Collapse</span>
				{:else}
					<ChevronRight size={18} class="opacity-60 group-hover:opacity-100" />
				{/if}
			</button>
		</div>
	</aside>

	<!-- Main Content Area -->
	<main class="flex-1 flex flex-col relative overflow-hidden">
		<!-- Dynamic Scan Status Overlay (Global) -->
		<ScanStatusOverlay />

		<div class="flex-1 overflow-y-auto p-8 lg:p-10 relative">
			<!-- Animated Background Glow -->
			<div class="absolute -top-24 -right-24 w-96 h-96 bg-blue-600/5 rounded-full blur-[120px] pointer-events-none"></div>
			<div class="absolute -bottom-24 -left-24 w-96 h-96 bg-blue-600/5 rounded-full blur-[120px] pointer-events-none"></div>

			{@render children()}
		</div>
	</main>
</div>

<!-- Global Shortcut Help -->
{#if showShortcuts}
	<div class="fixed inset-0 z-[2000] bg-black/90 backdrop-blur-xl flex items-center justify-center p-6 animate-in fade-in duration-500">
		<div class="w-[600px] bg-bg-secondary border border-white/10 rounded-3xl p-12 shadow-2xl relative overflow-hidden">
			<div class="absolute inset-0 bg-gradient-to-br from-blue-600/5 to-transparent pointer-events-none"></div>

			<div class="flex justify-between items-start mb-12">
				<div>
					<h2 class="text-2xl font-bold text-text-primary">Global Command Palette</h2>
					<p class="text-xs font-medium text-text-secondary mt-2 opacity-60">Terminal-grade keyboard interfaces</p>
				</div>
				<button onclick={() => showShortcuts = false} class="text-text-secondary hover:text-white transition-colors">
					<Library size={24} class="rotate-45" />
				</button>
			</div>

			<div class="grid grid-cols-2 gap-x-12 gap-y-6">
				<div class="space-y-4">
					<h3 class="text-4xs font-bold uppercase text-text-secondary opacity-40">Navigation</h3>
					<div class="flex justify-between items-center"><span class="text-xs font-semibold text-text-primary">Overview</span> <kbd class="px-2 py-1 bg-bg-tertiary border border-border-color rounded text-4xs mono">D</kbd></div>
					<div class="flex justify-between items-center"><span class="text-xs font-semibold text-text-primary">Insights</span> <kbd class="px-2 py-1 bg-bg-tertiary border border-border-color rounded text-4xs mono">G</kbd></div>
					<div class="flex justify-between items-center"><span class="text-xs font-semibold text-text-primary">Archive Index</span> <kbd class="px-2 py-1 bg-bg-tertiary border border-border-color rounded text-4xs mono">I</kbd></div>
					<div class="flex justify-between items-center"><span class="text-xs font-semibold text-text-primary">Filesystem</span> <kbd class="px-2 py-1 bg-bg-tertiary border border-border-color rounded text-4xs mono">T</kbd></div>
					<div class="flex justify-between items-center"><span class="text-xs font-semibold text-text-primary">Jobs</span> <kbd class="px-2 py-1 bg-bg-tertiary border border-border-color rounded text-4xs mono">A</kbd></div>
				</div>
				<div class="space-y-4">
					<h3 class="text-4xs font-bold uppercase text-text-secondary opacity-40">Operations</h3>
					<div class="flex justify-between items-center"><span class="text-xs font-semibold text-text-primary">Media Inventory</span> <kbd class="px-2 py-1 bg-bg-tertiary border border-border-color rounded text-4xs mono">M</kbd></div>
					<div class="flex justify-between items-center"><span class="text-xs font-semibold text-text-primary">Data Recovery</span> <kbd class="px-2 py-1 bg-bg-tertiary border border-border-color rounded text-4xs mono">R</kbd></div>
					<div class="flex justify-between items-center"><span class="text-xs font-semibold text-text-primary">System Settings</span> <kbd class="px-2 py-1 bg-bg-tertiary border border-border-color rounded text-4xs mono">S</kbd></div>
					<div class="flex justify-between items-center"><span class="text-xs font-semibold text-text-primary">Command Help</span> <kbd class="px-2 py-1 bg-bg-tertiary border border-border-color rounded text-4xs mono">?</kbd></div>
				</div>
			</div>

			<footer class="mt-16 pt-8 border-t border-white/[0.03] text-center">
				<p class="text-3xs font-medium text-text-secondary opacity-40 italic">Use keyboard shortcuts for quick navigation.</p>
			</footer>
		</div>
	</div>
{/if}

<style>
	:global(body) {
		font-feature-settings: "cv02", "cv03", "cv04", "cv11";
	}

	::-webkit-scrollbar {
		width: 6px;
		height: 6px;
	}

	::-webkit-scrollbar-track {
		background: transparent;
	}

	::-webkit-scrollbar-thumb {
		background: rgba(255, 255, 255, 0.05);
		border-radius: 10px;
	}

	::-webkit-scrollbar-thumb:hover {
		background: rgba(255, 255, 255, 0.1);
	}
</style>
le>
