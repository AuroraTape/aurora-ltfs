/*
**
**  OO_Copyright_BEGIN
**
**
**  Copyright 2026 Aurora Tape Project contributors. All rights reserved.
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
**  OO_Copyright_END
**
*************************************************************************************
**
** COMPONENT NAME:  Aurora LTFS
**
** FILE NAME:       changer_drivers/smc_sense.h
**
** DESCRIPTION:     Sense data of a medium changer mapped to the EDEV_* codes.
**                  Shared by every changer plugin: the SCSI ones map the
**                  sense they receive, the file emulation maps the sense a
**                  test injects.
**
*************************************************************************************
*/

#ifndef __smc_sense_h
#define __smc_sense_h

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Map a sense value (sense key << 16 | ASC << 8 | ASCQ) to a negative EDEV_*
 * code. Codes the table does not list fall back to the generic code of their
 * sense key. The description, when known, is returned through msg.
 */
int smc_sense_to_errorcode(uint32_t sense, const char **msg);

/** Parse "SK/ASCASCQ" (e.g. "05/3B0D" or "5/3b0d") into a sense value. -1 when malformed. */
int smc_parse_sense_string(const char *str, uint32_t *sense);

#ifdef __cplusplus
}
#endif

#endif /* __smc_sense_h */
