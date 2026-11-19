/*
**
**  AA_Copyright_BEGIN
**
**
**  Copyright 2026,      Aurora Tape Project contributors. All rights reserved.
**
**  Redistribution and use in source and binary forms, with or without
**   modification, are permitted provided that the following conditions
**  are met:
**  1. Redistributions of source code must retain the above copyright
**     notice, this list of conditions and the following disclaimer.
**  2. Redistributions in binary form must reproduce the above copyright
**     notice, this list of conditions and the following disclaimer in the
**  documentation and/or other materials provided with the distribution.
**  3. Neither the name of the copyright holder nor the names of its
**     contributors may be used to endorse or promote products derived from
**     this software without specific prior written permission.
**
**  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS ``AS IS''
**  AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
**  IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
**  ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
**  LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
**  CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
**  SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
**  INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
**  CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
**  ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
**  POSSIBILITY OF SUCH DAMAGE.
**
**
**  AA_Copyright_END
**
*************************************************************************************
**
** FILE NAME:       index_cache.h
**
** DESCRIPTION:     Index cache: a copy of the last index on disk that a volume can be
**                  mounted from (see index_cache.c).
**
*************************************************************************************
*/

#ifndef __index_cache_h__
#define __index_cache_h__

#include <stdbool.h>
#include <stdint.h>

struct ltfs_volume;

bool index_cache_enabled(struct ltfs_volume *vol);
int  index_cache_setup(struct ltfs_volume *vol);
int  index_cache_mount(uint64_t vcr, struct ltfs_volume *vol);
void index_cache_refresh(uint64_t vcr, struct ltfs_volume *vol);
void index_cache_invalidate(struct ltfs_volume *vol);
void index_cache_written(struct ltfs_volume *vol);

#endif /* __index_cache_h__ */
