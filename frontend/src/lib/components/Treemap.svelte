<script lang="ts">
    import { onMount } from 'svelte';
    import ContextMenu from './ui/ContextMenu.svelte';
    import EmptyState from './ui/EmptyState.svelte';
    import { FolderSearch, ExternalLink, ChevronLeft } from 'lucide-svelte';
    import type { TreemapItem } from '$lib/types';

    let { items = [], onSelect = null } = $props<{
        items: TreemapItem[];
        onSelect?: ((path: string) => void) | null;
    }>();

    let container: HTMLElement;
    let containerWidth = $state(100);
    let containerHeight = $state(100);

    // Zoom State
    let zoomStack = $state<TreemapItem[]>([]);
    const currentItems = $derived(zoomStack.length > 0 ? (zoomStack[zoomStack.length - 1].children || []) : items);
    const currentTitle = $derived(zoomStack.length > 0 ? zoomStack[zoomStack.length - 1].fullPath || zoomStack[zoomStack.length - 1].label : "Root");

    // Context Menu State
    let menuX = $state(0);
    let menuY = $state(0);
    let showMenu = $state(false);
    let contextItem = $state<TreemapItem | null>(null);

    onMount(() => {
        const resizeObserver = new ResizeObserver((entries) => {
            for (let entry of entries) {
                containerWidth = entry.contentRect.width;
                containerHeight = entry.contentRect.height;
            }
        });
        if (container) resizeObserver.observe(container);
        return () => resizeObserver.disconnect();
    });

    const colors = [
        'bg-blue-600', 'bg-purple-600', 'bg-orange-600',
        'bg-emerald-600', 'bg-rose-600', 'bg-cyan-600',
        'bg-amber-600', 'bg-fuchsia-600', 'bg-teal-600', 'bg-indigo-600'
    ];

    function computeRects(nodeItems: TreemapItem[], width: number, height: number, availableColors: string[]) {
        if (!nodeItems || nodeItems.length === 0 || width <= 0 || height <= 0) return [];
        let total = nodeItems.reduce((s, i) => s + i.value, 0);
        if (total <= 0) return [];

        let result = [];
        let x = 0, y = 0, w = width, h = height;

        for (let i = 0; i < nodeItems.length; i++) {
            const item = nodeItems[i];
            let ratio = item.value / total;
            let rectW, rectH;
            if (w > h) {
                rectW = w * ratio;
                rectH = h;
                result.push({ x, y, w: rectW, h: rectH, item, color: item.color || availableColors[i % availableColors.length] });
                x += rectW;
                w -= rectW;
            } else {
                rectW = w;
                rectH = h * ratio;
                result.push({ x, y, w: rectW, h: rectH, item, color: item.color || availableColors[i % availableColors.length] });
                y += rectH;
                h -= rectH;
            }
            total -= item.value;
        }
        return result;
    }

    const rects = $derived(computeRects(currentItems, containerWidth, containerHeight - (zoomStack.length > 0 ? 40 : 0), colors));

    function formatSize(bytes: number) {
        if (!bytes) return "0 B";
        const units = ["B", "KB", "MB", "GB", "TB"];
        let size = bytes, i = 0;
        while (size >= 1024 && i < 4) { size /= 1024; i++; }
        return `${size.toFixed(1)} ${units[i]}`;
    }

    function handleLeftClick(e: MouseEvent, item: TreemapItem) {
        e.stopPropagation();
        if (item.children && item.children.length > 0) {
            zoomStack.push(item);
        }
    }

    function handleRightClick(e: MouseEvent, item: TreemapItem) {
        e.preventDefault();
        e.stopPropagation();
        menuX = e.clientX;
        menuY = e.clientY;
        contextItem = item;
        showMenu = true;
    }

    function resetZoom() {
        zoomStack = [];
    }

    function popZoom() {
        zoomStack.pop();
    }
</script>

<div class="flex flex-col h-full w-full gap-2 min-h-0">
    <!-- Breadcrumbs / Zoom Control -->
    {#if zoomStack.length > 0}
        <div class="flex items-center gap-2 px-1">
            <button
                class="flex items-center gap-1 text-xs font-medium text-blue-400 hover:text-blue-300 transition-colors"
                onclick={popZoom}
            >
                <ChevronLeft size={14} /> Back
            </button>
            <div class="h-1 w-1 rounded-full bg-border-color"></div>
            <span class="text-xs font-medium text-text-secondary opacity-60 truncate">
                Focusing: {currentTitle}
            </span>
            <button
                class="ml-auto text-xs font-medium text-text-secondary hover:text-error-color opacity-40 hover:opacity-100 transition-all"
                onclick={resetZoom}
            >
                Reset view
            </button>
        </div>
    {/if}

    <div bind:this={container} class="flex-1 relative overflow-hidden rounded-xl bg-bg-primary border border-border-color/30 min-h-0">
        {#each rects as rect}
            {@render treeNode(rect.item, rect.x, rect.y, rect.w, rect.h, 0, rect.color)}
        {/each}

        {#if currentItems.length === 0}
            <EmptyState
                title="No nested data"
                class="absolute inset-0 p-0"
            />
        {/if}
    </div>
</div>

{#snippet treeNode(item: TreemapItem, x: number, y: number, w: number, h: number, depth: number, color: string)}
    <button
        type="button"
        class={`absolute flex flex-col text-left transition-all group overflow-hidden border border-white/5
                ${depth === 0 ? color + ' rounded-sm' : 'bg-black/20 hover:bg-black/10'}
                ${(item.children?.length || onSelect) ? 'cursor-pointer hover:ring-2 hover:ring-white/50 active:scale-[0.98]' : 'cursor-default'}`}
        style={`left: ${x}px; top: ${y}px; width: ${w}px; height: ${h}px;`}
        title={`${item.fullPath || item.label}: ${formatSize(item.value)}`}
        onclick={(e) => handleLeftClick(e, item)}
        oncontextmenu={(e) => handleRightClick(e, item)}
    >
        {#if w > 40 && h > 16}
            <div class={`px-1 py-0.5 shrink-0 ${depth === 0 ? 'bg-black/10' : ''}`}>
                <span class={`font-medium truncate w-full block text-[10px] drop-shadow-md ${depth === 0 ? 'text-white/90' : 'text-white/40'}`}>
                    {item.label}
                </span>
            </div>
        {/if}

        {#if item.children && item.children.length > 0 && w > 20 && h > 20}
            <div class="relative flex-1 w-full overflow-hidden">
                {#each computeRects(item.children, w, h - (w > 40 && h > 16 ? 18 : 0), [color]) as childRect}
                    {@render treeNode(childRect.item, childRect.x, childRect.y, childRect.w, childRect.h, depth + 1, color)}
                {/each}
            </div>
        {:else if w > 40 && h > 20}
            <div class="flex-1 flex items-center justify-center p-1">
                <span class="text-white/80 font-medium mono text-[9px] truncate w-full text-center drop-shadow-md">
                    {formatSize(item.value)}
                </span>
            </div>
        {/if}
    </button>
{/snippet}

<!-- Common Context Menu -->
<ContextMenu bind:show={showMenu} x={menuX} y={menuY}>
    <div class="flex flex-col p-1">
        <div class="px-3 py-2 border-b border-border-color/50 mb-1">
            <p class="text-xs font-semibold text-text-primary truncate max-w-[200px]">
                {contextItem?.label}
            </p>
        </div>

        {#if contextItem?.children?.length}
            <button
                class="flex items-center gap-3 px-3 py-2 text-sm font-medium text-text-primary hover:bg-blue-500/10 hover:text-blue-400 rounded-lg transition-all text-left"
                onclick={(e) => { handleLeftClick(e, contextItem!); showMenu = false; }}
            >
                <FolderSearch size={14} /> Focus directory
            </button>
        {/if}

        {#if onSelect && (contextItem?.fullPath || contextItem?.label)}
            <button
                class="flex items-center gap-3 px-3 py-2 text-sm font-medium text-text-primary hover:bg-success-color/10 hover:text-success-color rounded-lg transition-all text-left"
                onclick={() => { onSelect!(contextItem?.fullPath || contextItem!.label); showMenu = false; }}
            >
                <ExternalLink size={14} /> View in filesystem
            </button>
        {/if}
    </div>
</ContextMenu>
