<?php

declare(strict_types=1);

namespace HYT;

if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

class Duplicate_Checker {

    private const TITLE_SIMILARITY_THRESHOLD = 80;

    /**
     * Check if a piece of content is a duplicate.
     *
     * @return array{is_duplicate: bool, match_type: string, matched_post: \WP_Post|null, similarity: int}
     */
    public function check( string $title, string $content ): array {
        $result = [
            'is_duplicate' => false,
            'match_type'   => '',
            'matched_post' => null,
            'similarity'   => 0,
        ];

        // 1. Exact title match
        $exact = $this->exact_title_match( $title );
        if ( $exact ) {
            $result['is_duplicate'] = true;
            $result['match_type']   = 'exact_title';
            $result['matched_post'] = $exact;
            $result['similarity']   = 100;
            return $result;
        }

        // 2. Similar title match using similar_text()
        $similar = $this->similar_title_match( $title );
        if ( $similar ) {
            $result['is_duplicate'] = true;
            $result['match_type']   = 'similar_title';
            $result['matched_post'] = $similar['post'];
            $result['similarity']   = $similar['percent'];
            return $result;
        }

        // 3. Slug similarity
        $slug         = sanitize_title( $title );
        $slug_match   = $this->slug_match( $slug );
        if ( $slug_match ) {
            $result['is_duplicate'] = true;
            $result['match_type']   = 'slug_match';
            $result['matched_post'] = $slug_match;
            $result['similarity']   = 100;
            return $result;
        }

        return $result;
    }

    private function exact_title_match( string $title ): ?\WP_Post {
        $query = new \WP_Query( [
            'post_type'      => 'post',
            'post_status'    => [ 'publish', 'future', 'draft', 'pending', 'private' ],
            'title'          => $title,
            'posts_per_page' => 1,
            'fields'         => 'ids',
            'no_found_rows'  => true,
        ] );

        if ( $query->have_posts() ) {
            return get_post( $query->posts[0] );
        }

        // Fallback: LIKE query
        global $wpdb;
        $post_id = $wpdb->get_var(
            $wpdb->prepare(
                "SELECT ID FROM {$wpdb->posts}
                 WHERE post_title = %s
                   AND post_status IN ('publish','future','draft','pending','private')
                   AND post_type = 'post'
                 LIMIT 1",
                $title
            )
        );

        return $post_id ? get_post( (int) $post_id ) : null;
    }

    /**
     * @return array{post: \WP_Post, percent: int}|null
     */
    private function similar_title_match( string $title ): ?array {
        global $wpdb;

        // Get recent posts titles (last 1000 to keep it performant)
        $posts = $wpdb->get_results(
            "SELECT ID, post_title FROM {$wpdb->posts}
             WHERE post_status IN ('publish','future','draft','pending','private')
               AND post_type = 'post'
             ORDER BY ID DESC
             LIMIT 1000"
        );

        $title_lower = mb_strtolower( $title );

        foreach ( $posts as $post ) {
            $existing_lower = mb_strtolower( $post->post_title );
            $percent        = 0;
            similar_text( $title_lower, $existing_lower, $percent );

            if ( $percent >= self::TITLE_SIMILARITY_THRESHOLD ) {
                return [
                    'post'    => get_post( (int) $post->ID ),
                    'percent' => (int) round( $percent ),
                ];
            }
        }

        return null;
    }

    private function slug_match( string $slug ): ?\WP_Post {
        global $wpdb;

        $post_id = $wpdb->get_var(
            $wpdb->prepare(
                "SELECT ID FROM {$wpdb->posts}
                 WHERE post_name = %s
                   AND post_status IN ('publish','future','draft','pending','private')
                   AND post_type = 'post'
                 LIMIT 1",
                $slug
            )
        );

        return $post_id ? get_post( (int) $post_id ) : null;
    }
}
