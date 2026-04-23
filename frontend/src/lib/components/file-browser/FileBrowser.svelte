<script lang="ts">
        import {
                ChevronLeft,
                ChevronRight,
                ChevronUp,
                RotateCw,
                Search,
                Folder,
                Home,
                ArrowUpDown,
                MoreHorizontal,
                Plus,
                Scissors,
                Copy,
                Clipboard,
                Trash2,
                Type,
                LayoutGrid,
                CheckSquare,
                HardDrive,
                ShieldCheck,
                ShieldAlert,
                Square
        } from "lucide-svelte";
        import { Button } from "$lib/components/ui/button";
        import { Checkbox } from "$lib/components/ui/checkbox";
        import { ScrollArea } from "$lib/components/ui/scroll-area";
        import { Input } from "$lib/components/ui/input";
        import FileBrowserTreeItem from "./FileBrowserTreeItem.svelte";
        import FileBrowserRowItem from "./FileBrowserRowItem.svelte";
        import type { FileItem, Breadcrumb, TreeNode } from "$lib/types";
        import { cn } from "$lib/utils";

        let {
                currentPath = $bindable("/source_data"),
                files = [],
                onNavigate = (path: string) => {},
                onToggleTrack = (item: FileItem) => {},
                mode = "host"
        } = $props<{
                currentPath: string;
                files: FileItem[];
                onNavigate?: (path: string) => void;
                onToggleTrack?: (item: FileItem) => void;
                mode?: "host" | "index";
        }>();

        let searchQuery = $state("");
        let selectedPaths = $state<Set<string>>(new Set());
        let lastSelectedPath = $state<string | null>(null);
        let sortColumn = $state<"name" | "size" | "mtime" | "type">("name");
        let sortDirection = $state<"asc" | "desc">("asc");

        // --- Column Resizing Logic ---
        let mtimeWidth = $state(200);
        let typeWidth = $state(150);
        let sizeWidth = $state(120);

        let resizingCol = $state<string | null>(null);
        let startX = 0;
        let startWidth = 0;

        function startResize(e: MouseEvent, col: string) {
                e.preventDefault();
                resizingCol = col;
                startX = e.clientX;
                if (col === 'mtime') startWidth = mtimeWidth;
                else if (col === 'type') startWidth = typeWidth;
                else if (col === 'size') startWidth = sizeWidth;

                window.addEventListener('mousemove', handleMouseMove);
                window.addEventListener('mouseup', stopResize);
                document.body.style.cursor = 'col-resize';
        }

        function handleMouseMove(e: MouseEvent) {
                if (!resizingCol) return;
                const delta = e.clientX - startX;
                if (resizingCol === 'mtime') mtimeWidth = Math.max(100, startWidth + delta);
                else if (resizingCol === 'type') typeWidth = Math.max(80, startWidth + delta);
                else if (resizingCol === 'size') sizeWidth = Math.max(60, startWidth + delta);
        }

        function stopResize() {
                resizingCol = null;
                window.removeEventListener('mousemove', handleMouseMove);
                window.removeEventListener('mouseup', stopResize);
                document.body.style.cursor = '';
        }

        const colWidths = $derived({
                mtime: mtimeWidth,
                type: typeWidth,
                size: sizeWidth
        });

        // --- Navigation Tree Definition ---

        const sourceDataRoot = $derived({
                name: "Source Data",
                path: "/source_data",
                expanded: true,
                children: [],
                hasChildren: true
        });

        const virtualIndexRoot = $derived({
                name: "Virtual Index",
                path: "/",
                expanded: true,
                children: [],
                hasChildren: true
        });

        const activeRoot = $derived(mode === "host" ? sourceDataRoot : virtualIndexRoot);

        // --- Logic ---

        const breadcrumbs = $derived.by(() => {
                const parts = currentPath.split("/").filter(Boolean);
                const crumbs: Breadcrumb[] = [];

                if (mode === "host") {
                    crumbs.push({ name: "Source Data", path: "/source_data" });
                    let current = "/source_data";
                    const subParts = parts[0] === "source_data" ? parts.slice(1) : parts;
                    for (const part of subParts) {
                        current += `/${part}`;
                        crumbs.push({ name: part, path: current });
                    }
                } else {
                    crumbs.push({ name: "Virtual Index", path: "/" });
                    let current = "";
                    for (const part of parts) {
                        current += `/${part}`;
                        crumbs.push({ name: part, path: current });
                    }
                }
                return crumbs;
        });

        const filteredFiles = $derived.by(() => {
                let result = files.filter((f) => f.name.toLowerCase().includes(searchQuery.toLowerCase()));

                result.sort((a, b) => {
                        const valA = sortColumn === "type" ? a.type : a[sortColumn as keyof FileItem] || 0;
                        const valB = sortColumn === "type" ? b.type : b[sortColumn as keyof FileItem] || 0;

                        if (valA < valB) return sortDirection === "asc" ? -1 : 1;
                        if (valA > valB) return sortDirection === "asc" ? 1 : -1;
                        return 0;
                });

                return result;
        });

        function toggleSort(col: typeof sortColumn) {
                if (sortColumn === col) {
                        sortDirection = sortDirection === "asc" ? "desc" : "asc";
                } else {
                        sortColumn = col;
                        sortDirection = "asc";
                }
        }

        function handleRowClick(e: MouseEvent, item: FileItem) {
                if (e.shiftKey && lastSelectedPath) {
                        const lastIndex = filteredFiles.findIndex(f => f.path === lastSelectedPath);
                        const currentIndex = filteredFiles.findIndex(f => f.path === item.path);
                        const start = Math.min(lastIndex, currentIndex);
                        const end = Math.max(lastIndex, currentIndex);

                        const newSelection = new Set(selectedPaths);
                        for (let i = start; i <= end; i++) {
                                newSelection.add(filteredFiles[i].path);
                        }
                        selectedPaths = newSelection;
                } else if (e.metaKey || e.ctrlKey) {
                        const newSelection = new Set(selectedPaths);
                        if (newSelection.has(item.path)) {
                                newSelection.delete(item.path);
                        } else {
                                newSelection.add(item.path);
                        }
                        selectedPaths = newSelection;
                        lastSelectedPath = item.path;
                } else {
                        selectedPaths = new Set([item.path]);
                        lastSelectedPath = item.path;
                }
        }

        function handleRowDoubleClick(item: FileItem) {
                if (item.type === "directory") {
                        onNavigate(item.path);
                        selectedPaths = new Set();
                        lastSelectedPath = null;
                }
        }

        function handleSelectAll(checked: boolean) {
                if (checked) {
                        selectedPaths = new Set(filteredFiles.map(f => f.path));
                } else {
                        selectedPaths = new Set();
                }
        }

        function bulkToggle(track: boolean) {
                const selectedItems = files.filter(f => selectedPaths.has(f.path) && f.tracked !== track);
                selectedItems.forEach(item => onToggleTrack(item));
        }
</script>

<div
        class="file-browser flex h-full flex-col overflow-hidden rounded-lg border border-border-color bg-bg-secondary shadow-2xl"
>
        <!-- ZONE A: TOP BAR -->
        <div class="flex h-14 shrink-0 items-center justify-between border-b border-border-color bg-bg-tertiary/50 px-6 shadow-sm">
                <div class="flex items-center gap-4 flex-1">
                        <!-- Navigation Buttons -->
                        <div class="flex items-center gap-1">
                                <Button variant="ghost" size="icon" class="h-8 w-8 text-text-secondary hover:text-text-primary hover:bg-white/5">
                                        <ChevronLeft size={18}></ChevronLeft>
                                </Button>
                                <Button variant="ghost" size="icon" class="h-8 w-8 text-text-secondary hover:text-text-primary hover:bg-white/5">
                                        <ChevronRight size={18}></ChevronRight>
                                </Button>
                                <Button
                                        variant="ghost"
                                        size="icon"
                                        class="h-8 w-8 text-text-secondary hover:text-text-primary hover:bg-white/5"
                                        onclick={() => {
                                                if (mode === "host" && currentPath === "/source_data") return;
                                                if (mode === "index" && currentPath === "/") return;
                                                const parent = currentPath.split("/").slice(0, -1).join("/") || "/";
                                                onNavigate(parent);
                                        }}
                                >
                                        <ChevronUp size={18}></ChevronUp>
                                </Button>
                        </div>

                        <!-- Address Bar -->
                        <div class="flex-1 flex items-center bg-bg-primary border border-border-color/40 rounded-md px-3 h-9 shadow-inner overflow-hidden max-w-3xl group transition-all focus-within:border-action-color/50">
                                <Folder size={16} class="text-yellow-500/80 mr-2 shrink-0"></Folder>
                                <div class="flex-1 flex items-center overflow-x-auto scrollbar-hide">
                                        {#each breadcrumbs as crumb, i}
                                                {#if i > 0}
                                                        <ChevronRight size={14} class="mx-1 text-text-secondary/30 shrink-0"></ChevronRight>
                                                {/if}
                                                <button
                                                        class={cn(
                                                                "px-2 py-0.5 rounded-md text-[13px] transition-colors hover:bg-white/5 whitespace-nowrap cursor-pointer",
                                                                i === breadcrumbs.length - 1 ? "text-text-primary font-bold" : "text-text-secondary hover:text-text-primary"
                                                        )}
                                                        onclick={() => onNavigate(crumb.path)}
                                                >
                                                        {crumb.name}
                                                </button>
                                        {/each}
                                </div>
                                <button class="ml-2 text-text-secondary hover:text-text-primary p-1 transition-colors cursor-pointer" onclick={() => onNavigate(currentPath)}>
                                        <RotateCw size={14}></RotateCw>
                                </button>
                        </div>
                </div>

                <!-- Search Input -->
                <div class="flex items-center shrink-0 ml-12">
                        <div class="relative w-64 sm:w-80 group">
                                <Search
                                        size={14}
                                        class="absolute left-3 top-3 text-text-secondary group-focus-within:text-action-color transition-colors"
                                ></Search>
                                <Input
                                        type="text"
                                        placeholder="Search folder"
                                        bind:value={searchQuery}
                                        class="h-9 bg-bg-primary/50 pl-10 text-[13px] placeholder:text-text-secondary/50 border-border-color/40 focus-visible:ring-action-color/40 transition-all rounded-md"
                                />
                        </div>
                </div>
        </div>

        <div class="flex flex-1 overflow-hidden">
                <!-- ZONE B: NAVIGATION PANE -->
                <aside class="flex w-72 shrink-0 flex-col border-r border-border-color bg-bg-secondary/50">
                        <ScrollArea class="flex-1 p-2">
                                <div class="px-3 py-1 text-[11px] font-bold uppercase tracking-widest text-text-secondary/60 mb-2">
                                        Navigation
                                </div>
                                <FileBrowserTreeItem node={activeRoot} selectedPath={currentPath} onSelect={onNavigate} isSpecial={true} {mode} />
                        </ScrollArea>
                </aside>

                <!-- ZONE C: DETAILS PANE -->
                <div class="flex min-w-0 flex-1 flex-col bg-bg-primary shadow-inner">
                        <!-- Column Headers -->
                        <div class="flex h-10 items-center border-b border-border-color bg-bg-tertiary/30 shrink-0 select-none">
                                <div class="flex w-12 shrink-0 justify-center">
                                        <Checkbox
                                                checked={selectedPaths.size === filteredFiles.length && filteredFiles.length > 0}
                                                onCheckedChange={handleSelectAll}
                                        />
                                </div>

                                <div class="flex flex-1 items-center min-w-0 h-full relative group/col">
                                        <button
                                                class="flex w-full items-center justify-between text-[11px] font-semibold text-text-secondary hover:bg-white/5 px-4 h-full transition-colors"
                                                onclick={() => toggleSort("name")}
                                        >
                                                Name
                                                {#if sortColumn === "name"}
                                                        <ArrowUpDown size={10} class={cn(sortDirection === "desc" && "rotate-180")}></ArrowUpDown>
                                                {/if}
                                        </button>
                                        <!-- Vertical Separator & Resizer -->
                                        <div class="absolute right-0 top-0 w-px h-full bg-border-color/30"></div>
                                        <div
                                                class="absolute -right-1 top-0 w-2 h-full cursor-col-resize z-10"
                                                role="none"
                                        ></div>
                                </div>

                                <div class="flex items-center h-full relative group/col shrink-0" style="width: {mtimeWidth}px">
                                        <button
                                                class="flex w-full items-center justify-between text-[11px] font-semibold text-text-secondary hover:bg-white/5 px-4 h-full transition-colors"
                                                onclick={() => toggleSort("mtime")}
                                        >
                                                Date modified
                                                {#if sortColumn === "mtime"}
                                                        <ArrowUpDown size={10} class={cn(sortDirection === "desc" && "rotate-180")}></ArrowUpDown>
                                                {/if}
                                        </button>
                                        <!-- Vertical Separator & Resizer -->
                                        <div class="absolute right-0 top-0 w-px h-full bg-border-color/30"></div>
                                        <div
                                                class="absolute -right-1 top-0 w-2 h-full cursor-col-resize z-10"
                                                onmousedown={(e) => startResize(e, 'mtime')}
                                                role="none"
                                        ></div>
                                </div>

                                <div class="flex items-center h-full relative group/col shrink-0" style="width: {typeWidth}px">
                                        <button
                                                class="flex w-full items-center justify-between text-[11px] font-semibold text-text-secondary hover:bg-white/5 px-4 h-full transition-colors"
                                                onclick={() => toggleSort("type")}
                                        >
                                                Type
                                                {#if sortColumn === "type"}
                                                        <ArrowUpDown size={10} class={cn(sortDirection === "desc" && "rotate-180")}></ArrowUpDown>
                                                {/if}
                                        </button>
                                        <!-- Vertical Separator & Resizer -->
                                        <div class="absolute right-0 top-0 w-px h-full bg-border-color/30"></div>
                                        <div
                                                class="absolute -right-1 top-0 w-2 h-full cursor-col-resize z-10"
                                                onmousedown={(e) => startResize(e, 'type')}
                                                role="none"
                                        ></div>
                                </div>

                                <div class="flex items-center h-full relative group/col shrink-0" style="width: {sizeWidth}px">
                                        <button
                                                class="flex w-full items-center justify-between text-[11px] font-semibold text-text-secondary hover:bg-white/5 px-4 h-full transition-colors text-right"
                                                onclick={() => toggleSort("size")}
                                        >
                                                Size
                                                {#if sortColumn === "size"}
                                                        <ArrowUpDown size={10} class={cn(sortDirection === "desc" && "rotate-180")}></ArrowUpDown>
                                                {/if}
                                        </button>
                                        <!-- Vertical Separator & Resizer -->
                                        <div class="absolute right-0 top-0 w-px h-full bg-border-color/30"></div>
                                        <div
                                                class="absolute -right-1 top-0 w-2 h-full cursor-col-resize z-10"
                                                onmousedown={(e) => startResize(e, 'size')}
                                                role="none"
                                        ></div>
                                </div>

                                <div class="w-10 shrink-0"></div>
                        </div>

                        <!-- Scrollable File List -->
                        <ScrollArea class="flex-1">
                                {#if filteredFiles.length === 0}
                                        <div class="flex h-full flex-col items-center justify-center p-12 text-center opacity-30">
                                                <Search size={48} class="mb-4" strokeWidth={1}></Search>
                                                <p class="text-sm font-medium uppercase tracking-widest">Folder is empty</p>
                                        </div>
                                {:else}
                                        {#each filteredFiles as item}
                                                <FileBrowserRowItem
                                                        {item}
                                                        {mode}
                                                        {colWidths}
                                                        isSelected={selectedPaths.has(item.path)}
                                                        onClick={(e) => handleRowClick(e, item)}
                                                        onDoubleClick={() => handleRowDoubleClick(item)}
                                                        onToggleTrack={() => onToggleTrack(item)}
                                                />
                                        {/each}
                                {/if}
                        </ScrollArea>
                </div>
        </div>

        <!-- ZONE D: STATUS BAR -->
        <div
                class="flex h-8 shrink-0 items-center justify-between border-t border-border-color bg-bg-tertiary px-6 text-[10px] font-medium text-text-secondary"
        >
                <div class="flex items-center gap-4">
                        <span>{filteredFiles.length} items</span>
                        <div class="h-3 w-px bg-border-color/40"></div>
                        {#if selectedPaths.size > 0}
                                <span class="text-text-primary">
                                        {selectedPaths.size} items selected
                                </span>
                        {/if}
                </div>
                <div class="flex items-center gap-3">
                        <div class="flex items-center gap-1.5 rounded-full bg-action-color/10 px-2 py-0.5 text-action-color border border-action-color/20 shadow-sm">
                                <CheckSquare size={10}></CheckSquare>
                                <span class="font-bold uppercase tracking-wider">
                                        {#if mode === 'host'}
                                                {files.filter((f) => f.tracked).length} Tracked
                                        {:else}
                                                {files.filter((f) => f.selected).length} Selected
                                        {/if}
                                </span>
                        </div>
                </div>
        </div>
</div>

<style>
        :global(.scrollbar-hide::-webkit-scrollbar) {
                display: none;
        }
        :global(.scrollbar-hide) {
                -ms-overflow-style: none;
                scrollbar-width: none;
        }
</style>
