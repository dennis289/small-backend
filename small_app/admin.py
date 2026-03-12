from django.contrib import admin
from .models import *
# Register your models here.
admin.site.register(Roles)
admin.site.register(Persons)
admin.site.register(Events)
admin.site.register(Rosters)
admin.site.register(Assignment)
admin.site.register(User)

from .models import AwardType, Award, RosterFeedback
admin.site.register(AwardType)
admin.site.register(Award)
admin.site.register(RosterFeedback)
