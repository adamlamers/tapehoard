<script lang="ts">
	import { cn } from "$lib/utils";
	import type { HTMLAttributes } from "svelte/elements";

	let { class: className, children, ...rest }: HTMLAttributes<HTMLParagraphElement> = $props();
</script>

<p
	class={cn("text-xs text-text-secondary", className)}
	{...rest}
>
	{@render children?.()}
</p>
